"""Relocatable, scalar ISA48 Glasshouse engine and encoded audio harness.

The emitter translates a deliberately small expression language to real SHARC
instructions. SSIM executes those instructions; no host math substitutes for an
audio callback. State is always relative to I0 (or the per-channel I6), with
no absolute data pointers or dynamically allocated storage.
"""
import ast
from functools import lru_cache
import math
from pathlib import Path

import sasm
import ssim
import glasshouse_state as state

ENTRY = 'GLASSHOUSE_PROCESS'
STATE_WORDS = state.STATE_WORDS
CHANNELS = state.CHANNELS
INITIALIZED = state.INITIALIZED
MATH_ASM = Path(__file__).resolve().parents[2] / 'src/sharc/glasshouse_math.asm'

# Persistent globals; channel words are deliberately independent of compiler
# locals. Other runtime state and temporary expression spills are private.
GLOBAL = {**{f'smooth{i}':64+i for i in range(6)}, 'phase':70,'ramp_phase':71,
          'bypass_mix':72,'sag_mix':73,
          'attack_seconds':76,'release_seconds':77,'attack_coeff':78,'release_coeff':79,
          'gate_release':80,'gate_threshold':81,'swell_in_step':82,'swell_out_step':83,
          'sc_g':84,'eq_g':85,'motion_hz':86,'ramp_hz':87,'emphasis':88,
          'threshold':89,'dynamics':90,'ratio':91,'sag_amount':92,'attack_scale':93,
          'volume_motion0':94,'volume_motion1':95,'eq_motion0':96,'eq_motion1':97,
          'pan_motion0':98,'pan_motion1':99,'frame':100,'ch':101,
          'manual_dip0':145,'manual_dip1':177,
          'sc_inverse':102,'pre_inverse':103,'post_g':104,'post_inverse':105,
          'emphasis_inverse':106,'threshold_inverse':107,'ratio_curve':108,
          'settings_valid':109,'spread_inverse':110,'motion_base':111,'spread_motion':112}
CHANNEL = {name:i for i,name in enumerate(('sidechain','pre','post','eq','clip','envelope',
           'slow','reduction','spring','velocity','activity','gate','swell','sag_gain',
           'attack','release','filter_g','manual_dip'))}
CHANNEL['filter_inverse'] = 25
# Caller-spilled registers cache smoothed controls throughout one16-frame block.
CACHED = {f'smooth{i}':6+i for i in range(6)}
PARAMS = {**{f'k{p}{i}':(state.knob(p,i),False) for p in range(4) for i in range(6)},
          **{f't{p}{i}':(state.toggle(p,i),True) for p in range(4) for i in range(3)},
          'aux':(state.AUX,True),'sag':(state.SAG,True),'enable':(state.ENABLE,True)}


class _Emitter:
    """Compile a fixed, auditable arithmetic/control subset; all values binary32."""
    def __init__(self):
        self.lines=[]
        self.locals={}
        self.serial=0
        self.depth=0
    def line(self,*lines): self.lines.extend(lines)
    def label(self,prefix='gh_branch'):
        self.serial+=1
        return f'{prefix}_{self.serial}'
    def location(self,node):
        if isinstance(node,ast.Attribute) and isinstance(node.value,ast.Name) and node.value.id=='c':
            return CHANNEL[node.attr],'I6',False
        name=node.id if isinstance(node,ast.Name) else node
        if name in PARAMS:
            offset,integer=PARAMS[name]
            return offset,'I0',integer
        if name in GLOBAL: return GLOBAL[name],'I0',False
        if name not in self.locals:
            self.locals[name]=256+len(self.locals)
            if self.locals[name]>=356: raise ValueError('Glasshouse compiler local arena overflow')
        return self.locals[name],'I0',False
    def load(self,node,register=0):
        name=node.id if isinstance(node,ast.Name) else node
        if isinstance(name,str) and name in CACHED:
            if register != CACHED[name]: self.line(f'F{register} = F{CACHED[name]};')
            return
        offset,base,integer=self.location(node)
        self.line(f'R{register} = DM({offset},{base});')
        if integer: self.line(f'F{register} = FLOAT R{register};')
    def leaf(self,node):
        return isinstance(node,(ast.Constant,ast.Name,ast.Attribute))
    def leaf_to(self,node,register):
        if isinstance(node,ast.Constant): self.line(f'R{register} = {float(node.value)!r};')
        else: self.load(node,register)
    def store(self,node):
        name=node.id if isinstance(node,ast.Name) else node
        if isinstance(name,str) and name in CACHED:
            register=CACHED[name]
            if self.lines and self.lines[-1].startswith('F0 = '):
                self.lines[-1]=self.lines[-1].replace('F0 = ',f'F{register} = ',1)
            else: self.line(f'F{register} = F0;')
            return
        offset,base,integer=self.location(node)
        if integer: raise ValueError('the audio engine cannot overwrite native parameters')
        self.line(f'DM({offset},{base}) = F0;')
    def push(self):
        offset=360+self.depth
        self.depth+=1
        if self.depth>20: raise ValueError('Glasshouse expression stack overflow')
        self.line(f'DM({offset},I0) = F0;')
        return offset
    def pop(self,offset):
        self.depth-=1
        self.line(f'F1 = DM({offset},I0);')
    def expr(self,n):
        if isinstance(n,ast.Constant):
            v=float(n.value)
            self.line(f'R0 = {v!r};')
        elif isinstance(n,(ast.Name,ast.Attribute)):
            self.load(n)
        elif isinstance(n,ast.UnaryOp):
            if isinstance(n.op,ast.USub):
                self.expr(n.operand);self.line('F0 = -F0;')
            elif isinstance(n.op,ast.Not):
                self.expr(ast.IfExp(n.operand,ast.Constant(0.),ast.Constant(1.)))
            else: raise ValueError(ast.dump(n))
        elif isinstance(n,ast.BinOp):
            op={ast.Add:'+',ast.Sub:'-',ast.Mult:'*',ast.Div:'*'}.get(type(n.op))
            if op is None: raise ValueError(ast.dump(n))
            if isinstance(n.op,ast.Div) and isinstance(n.right,ast.Constant):
                self.expr(n.left);self.line(f'F1 = {1.0/float(n.right.value)!r};','F0 = F0 * F1;')
            elif self.leaf(n.right):
                self.expr(n.left)
                if isinstance(n.op,ast.Div):
                    self.line('F4 = F0;');self.expr(n.right);self.line('CALL gh_recip;','F0 = F4 * F0;')
                else:
                    self.leaf_to(n.right,1);self.line(f'F0 = F0 {op} F1;')
            elif isinstance(n.left,ast.Constant) and not isinstance(n.op,ast.Div):
                self.expr(n.right);self.leaf_to(n.left,1);self.line(f'F0 = F1 {op} F0;')
            else:
                self.expr(n.left);temp=self.push();self.expr(n.right)
                if isinstance(n.op,ast.Div):self.line('CALL gh_recip;')
                self.pop(temp);self.line(f'F0 = F1 {op} F0;')
        elif isinstance(n,ast.IfExp):
            other,end=self.label(),self.label()
            self.condition(n.test,other)
            self.expr(n.body);self.line(f'JUMP {end};',f'{other}:')
            self.expr(n.orelse);self.line(f'{end}:')
        elif isinstance(n,ast.Compare):
            if self.leaf(n.comparators[0]):
                self.expr(n.left);self.leaf_to(n.comparators[0],1);self.line('COMP(F0,F1);')
            else:
                self.expr(n.left);temp=self.push();self.expr(n.comparators[0]);self.pop(temp);self.line('COMP(F1,F0);')
            cond={ast.Eq:'EQ',ast.NotEq:'NE',ast.Lt:'LT',ast.LtE:'LE',ast.Gt:'GT',ast.GtE:'GE'}[type(n.ops[0])]
            self.line('R0 = 0.0;','R1 = 1.0;',f'IF {cond} F0 = PASS F1;')
        elif isinstance(n,ast.BoolOp):
            # Both operands have no writes or externally observable side effects.
            self.expr(n.values[0])
            for rhs in n.values[1:]:
                temp=self.push();self.expr(rhs);self.pop(temp)
                op='MIN' if isinstance(n.op,ast.And) else 'MAX'
                self.line(f'F0 = {op}(F1,F0);')
        elif isinstance(n,ast.Call): self.call(n)
        else: raise ValueError(f'unsupported Glasshouse expression {ast.dump(n)}')
    def condition(self,node,false):
        if isinstance(node,ast.Compare):
            self.expr(node.left)
            if self.leaf(node.comparators[0]):
                self.leaf_to(node.comparators[0],1);self.line('COMP(F0,F1);')
            else:
                temp=self.push();self.expr(node.comparators[0]);self.pop(temp);self.line('COMP(F1,F0);')
            cond={ast.Eq:'NE',ast.NotEq:'EQ',ast.Lt:'GE',ast.LtE:'GT',ast.Gt:'LE',ast.GtE:'LT'}[type(node.ops[0])]
            self.line(f'IF {cond} JUMP {false};')
        elif isinstance(node,ast.BoolOp) and isinstance(node.op,ast.And):
            for value in node.values:self.condition(value,false)
        elif isinstance(node,ast.BoolOp) and isinstance(node.op,ast.Or):
            success=self.label()
            for value in node.values[:-1]:
                following=self.label();self.condition(value,following)
                self.line(f'JUMP {success};',f'{following}:')
            self.condition(node.values[-1],false);self.line(f'{success}:')
        elif isinstance(node,ast.UnaryOp) and isinstance(node.op,ast.Not):
            self.expr(node.operand);self.line('F1 = 0.0;','COMP(F0,F1);',f'IF NE JUMP {false};')
        else:
            self.expr(node);self.line('F1 = 0.0;','COMP(F0,F1);',f'IF EQ JUMP {false};')
    def call(self,n):
        name=n.func.id
        if name in ('exp','log','log1p','sin','tan','recip'):
            self.expr(n.args[0]);self.line(f'CALL gh_{name};');return
        if name=='cos':
            self.expr(n.args[0]);self.line('F1 = 1.5707963267948966;','F0 = F0 + F1;','CALL gh_sin;');return
        if name=='divide':
            self.expr(n.args[0]);temp=self.push();self.expr(n.args[1])
            self.line('F1 = F0;',f'F0 = DM({temp},I0);','CALL gh_divide;');self.depth-=1;return
        if name=='abs': self.expr(n.args[0]);self.line('F0 = ABS F0;');return
        if name in ('min','max'):
            if self.leaf(n.args[1]):
                self.expr(n.args[0]);self.leaf_to(n.args[1],1)
                self.line(f'F0 = {name.upper()}(F0,F1);')
            else:
                self.expr(n.args[0]);temp=self.push();self.expr(n.args[1]);self.pop(temp)
                self.line(f'F0 = {name.upper()}(F1,F0);')
            return
        if name=='clamp':
            args=n.args if len(n.args)==3 else [n.args[0],ast.Constant(0.),ast.Constant(1.)]
            self.call(ast.Call(ast.Name('min'),[ast.Call(ast.Name('max'),args[:2],[]),args[2]],[]));return
        if name=='L':
            # Fixed endpoint ratios are reduced at build time, never on host at audio time.
            value,lo,hi=n.args
            low,high=float(ast.literal_eval(lo)),float(ast.literal_eval(hi))
            f32=lambda x:ssim.b2f(ssim.f2b(x))
            scale=math.log(f32(f32(high)/f32(low)))
            self.expr(ast.Call(ast.Name('clamp'),[value],[]))
            self.line(f'F1 = {scale!r};','F0 = F0 * F1;','CALL gh_exp;',f'F1 = {low!r};','F0 = F0 * F1;');return
        if name=='db':
            self.expr(n.args[0]);self.line('F1 = 0.11512925465;','F0 = F0 * F1;','CALL gh_exp;');return
        if name=='gain_db':
            self.call(ast.Call(ast.Name('max'),[n.args[0],ast.Constant(1.e-12)],[]))
            self.line('CALL gh_log;','F1 = 8.685889638;','F0 = F0 * F1;');return
        if name=='pole':
            arg=ast.BinOp(ast.UnaryOp(ast.USub(),ast.Constant(1.)),ast.Div(),ast.BinOp(n.args[0],ast.Mult(),ast.Constant(48000.)))
            self.expr(arg);self.line('CALL gh_exp;');return
        if name=='follow':
            value,target,attack,release=n.args
            if self.leaf(target):self.leaf_to(target,1)
            else:
                self.expr(target);self.line('F12 = F0;','F1 = F12;')
            self.load(value)
            self.leaf_to(release,3)
            if ast.dump(attack)!=ast.dump(release):
                self.leaf_to(attack,2);self.line('COMP(F1,F0);','IF GT F3 = PASS F2;')
            self.line('F0 = F0 - F1;','F0 = F0 * F3;','F0 = F0 + F1;')
            return
        if name=='adaa':
            self.expr(n.args[0]);self.line('CALL gh_adaa;');return
        if name=='low' and len(n.args)==4:
            value,g,z,inverse=n.args
            self.expr(value);self.load(z,1);self.leaf_to(g,2);self.leaf_to(inverse,3)
            self.line('F0 = F0 - F1;','F0 = F0 * F2;','F0 = F0 * F3;',
                      'F2 = F0;','F0 = F0 + F1;','F1 = F0 + F2;')
            offset,base,_=self.location(z);self.line(f'DM({offset},{base}) = F1;');return
        raise ValueError(f'unsupported Glasshouse intrinsic {name}')
    def statements(self,source):
        nodes=ast.parse(source).body if isinstance(source,str) else source
        for n in nodes:
            if isinstance(n,ast.Assign):
                self.expr(n.value);self.store(n.targets[0])
            elif isinstance(n,ast.If):
                other,end=self.label(),self.label()
                self.condition(n.test,other);self.statements(n.body)
                self.line(f'JUMP {end};',f'{other}:');self.statements(n.orelse);self.line(f'{end}:')
            else: raise ValueError(f'unsupported Glasshouse statement {ast.dump(n)}')


SETTINGS = '''
attack_seconds = L(k03,0.0005,0.3)
release_seconds = 0.05 if t00 == 0 else (1.5 if t00 == 2 else L(k14,0.05,1.5))
attack_coeff = pole(attack_seconds)
release_coeff = pole(release_seconds)
gate_release = pole(L(k11,0.02,1.5))
gate_threshold = db(-80.0 + 50.0*k10)
swell_in_step = 1.0 / (L(k12,0.01,4.0)*48000.0)
swell_out_step = 1.0 / (L(k13,0.01,4.0)*48000.0)
sc_g = tan(3.141592653589793*L(k15,20.0,1200.0)/48000.0)
eq_g = 0.06225760507447121
motion_hz = L(1.0-k03,0.08,12.0)
ramp_hz = L(k21,0.03,8.0)
emphasis = t12*0.5
sc_inverse = 1.0/(1.0+sc_g)
pre_inverse = 1.0/(1.0+eq_g)
emphasis_inverse = 1.0/(1.0+emphasis)
post_g = eq_g*emphasis_inverse
post_inverse = 1.0/(1.0+post_g)
'''

SAMPLE = '''
sag_mix = sag + 0.9995834201268338*(sag_mix-sag)
sidechain = t20 == 2
mono = t20 != 1
spread = t22 == 2
volume_spread = spread and t11 != 0
eq_spread = spread and t11 != 2
independent = t22 == 1 or volume_spread
depth = k20
audio0 = raw_left
audio1 = raw_left if mono else raw_right
detector0 = raw_right if sidechain else audio0
detector1 = raw_right if sidechain else audio1
phase = phase + motion_hz/48000.0
if phase >= 1.0:
    phase = phase-1.0
ramp_phase = ramp_phase+ramp_hz/48000.0
if t30 == 2 and ramp_phase >= 1.0:
    ramp_phase = ramp_phase-1.0
else:
    if t30 != 2:
        ramp_phase = clamp(ramp_phase)
ramp = 1.0-abs(2.0*ramp_phase-1.0) if t30 == 2 else clamp(ramp_phase)
if t32 == 1:
    ramp = 0.5-0.5*cos(3.141592653589793*ramp)
if t32 == 2:
    ramp = 1.0 if ramp >= 0.5 else 0.0
if t31 == 1:
    ramp = 1.0-ramp
'''

CONTROL = '''
if frame == 0:
    threshold = db(-6.0-48.0*smooth0)
    dynamics = smooth1+sag_mix*(1.0-smooth1)
    ratio = L(dynamics*2.0,1.0,20.0) if dynamics < 0.5 else L((dynamics-0.5)*4.0,20.0,100.0)
    sag_amount = clamp((dynamics-0.75)*4.0)
    attack_scale = L(smooth3,0.0005,0.3)/attack_seconds
    threshold_inverse = 1.0/threshold
    ratio_curve = 1.0-1.0/ratio
    if k23 > 0.5 or t01 == 2 or eq_spread:
        motion_base = sin(6.283185307179586*phase)
        if width == 2 and ((k23 > 0.5 and volume_spread) or (t01 == 2 and eq_spread)):
            spread_motion = sin(6.283185307179586*phase+3.141592653589793*depth)
    if k23 > 0.5:
        volume_motion0 = motion_base
        if width == 2:
            volume_motion1 = spread_motion if volume_spread else motion_base
    if t01 == 2:
        eq_motion0 = motion_base
        if width == 2:
            eq_motion1 = spread_motion if eq_spread else motion_base
    if eq_spread:
        pan_motion0 = motion_base
        if width == 2:
            pan_motion1 = sin(6.283185307179586*phase+3.141592653589793)
wet_gain = smooth2*smooth2*4.0
dry_gain = smooth5*smooth5*4.0
'''

SENSE = '''
sc_low = low(detector,sc_g,c.sidechain,sc_inverse)
sc = detector if k15 < 0.005 else detector-sc_low
sensed = abs(sc)
'''

CHANNEL_BODY = '''
c.envelope = follow(c.envelope,sensed,0.9793821813312401,0.9993057966773692)
c.slow = follow(c.slow,sensed,0.9998958387584922,0.9998958387584922)
triggered = c.envelope > threshold
c.activity = follow(c.activity,triggered,attack_coeff,release_coeff)
x = audio
pre_low = low(x,eq_g,c.pre,pre_inverse)
x = x+emphasis*(x-pre_low)
sag_ratio = c.envelope*threshold_inverse
if ratio_curve == 0.0 or c.envelope <= threshold:
    target_db = 0.0
else:
    target_db = clamp(gain_db(sag_ratio)*ratio_curve,0.0,72.0)
if k23 > 0.5:
    target_db = target_db*(0.5+0.5*volume_motion)
transient = clamp(c.envelope/(c.slow+0.000001)-1.0,0.0,5.0)
if frame == 0:
    c.attack = pole(attack_seconds*attack_scale/(1.0+transient*3.0 if t10 == 2 else 1.0)) if t10 == 2 or attack_scale != 1.0 else attack_coeff
    c.release = pole(release_seconds/(1.0+transient*2.0)) if t10 != 0 else release_coeff
c.reduction = follow(c.reduction,target_db,c.attack,c.release)
gr = c.reduction
if t02 != 1:
    wild = t02 == 2
    omega = 69.11503837897544 if wild else 18.84955592153876
    damping = 0.12 if wild else 0.38
    spring_target = clamp(c.reduction/24.0)
    c.velocity = c.velocity+(omega*omega*(spring_target-c.spring)-2.0*damping*omega*c.velocity)/48000.0
    c.spring = c.spring+c.velocity/48000.0
    gr = gr+(c.spring-spring_target)*(14.0 if wild else 5.0)
gr = clamp(gr,0.0,72.0)
sag_gain = 1.0 if sag_amount == 0.0 else 1.0/(1.0+sag_amount*6.0*sag_ratio*sag_ratio)
c.sag_gain = sag_gain+0.9995834201268338*(c.sag_gain-sag_gain)
x = x*db(-gr)*c.sag_gain
post_low = low(x,post_g,c.post,post_inverse)
x = post_low+(x-post_low)*emphasis_inverse
eq = (smooth4-0.5)*2.0
if abs(eq) < 0.025:
    eq = 0.0
if t01 == 0:
    eq = eq*(1.0-c.activity)
if t01 == 2:
    eq = eq*(1.0-0.65*c.activity*(0.5+0.5*eq_motion))
if frame == 0:
    cutoff = L(1.0+eq,220.0,18000.0) if eq < 0.0 else L(eq,25.0,2200.0)
    c.filter_g = tan(3.141592653589793*cutoff/48000.0)
    c.filter_inverse = 1.0/(1.0+c.filter_g)
eq_low = low(x,c.filter_g,c.eq,c.filter_inverse)
filtered = eq_low if eq < 0.0 else x-eq_low
x = x+clamp(abs(eq)*8.0)*(filtered-x)
if eq_spread:
    x = x*(1.0-depth*c.activity*0.45*(1.0+pan_motion))
c.gate = follow(c.gate,1.0 if c.envelope >= gate_threshold else 0.0,0.9896373989149966,gate_release)
manual = t21 == 1
auto_swell = t21 == 2 or (aux and not manual)
swell_target = (0.0 if aux or c.manual_dip else 1.0) if manual else ((1.0 if triggered else 0.0) if auto_swell else 1.0)
scale_inverse = spread_inverse if ch == 1.0 else 1.0
c.swell = c.swell+clamp(swell_target-c.swell,-swell_out_step*scale_inverse,swell_in_step*scale_inverse)
if c.swell <= 0.0:
    c.manual_dip = 0.0
y = (x*wet_gain+audio*dry_gain)*c.swell
if k22 > 0.5:
    y = y*c.gate
if k24 > 0.5:
    ceiling = db(-3.0-27.0*smooth0)
    clip_input = divide(y,ceiling)
    y = ceiling*adaa(clip_input)
else:
    ceiling = 0.98+dynamics*(0.75-0.98)
    y = clamp(y,-ceiling,ceiling)
'''


def source(base):
    e=_Emitter();e.line('.equ PEYEN, 0x200000','.equ BDCST9, 0x400000','.equ RND32,0x10000','.equ TRUNCATE,0x8000',f'.section pm {base:#x}',ENTRY+':')
    e.line('DM(416,I0) = MODE1;','BIT CLR MODE1 PEYEN | BDCST9;','BIT SET MODE1 RND32;','BIT CLR MODE1 TRUNCATE;')
    for r in range(16):e.line(f'DM({400+r},I0) = R{r};')
    for j,reg in enumerate(('ASTATX','ASTATY','STKYX','STKYY','I4','L4','I5','L5','I6','L6')):
        e.line(f'R0 = {reg};',f'DM({417+j},I0) = R0;')
    e.line('L4 = 0;','L5 = 0;','L6 = 0;','I4 = I1;','I5 = I2;','R0 = DM(4,I0);','R0 = PASS R0;','IF NE JUMP gh_initialized;')
    # Bounded scalar initialization excludes parameters and register spill arena.
    e.line('I6 = I0;','MODIFY(I6,64);','R0 = 0;','R1 = 336;','gh_clear:','DM(I6,1) = R0;','R1 = R1 - 1;','IF NE JUMP gh_clear;','R0 = 1;','DM(4,I0) = R0;')
    for i in range(6):e.line(f'R0 = DM({16+i},I0);',f'DM({64+i},I0) = R0;')
    for ch in range(2):
        for name in ('gate','swell','sag_gain'):e.line('R0 = 1.0;',f'DM({state.CHANNEL_BASE+state.CHANNEL_STRIDE*ch+CHANNEL[name]},I0) = R0;')
    e.line('gh_initialized:')
    for i in range(6):e.line(f'F{6+i} = DM({64+i},I0);')
    # Only these ten raw controls enter Settings-derived coefficients. Their
    # bitwise snapshot makes unchanged blocks cheap without changing update
    # timing or any optional filter/envelope history.
    setting_words=(19,40,26,23,22,24,25,27,29,45)
    e.line('R0 = DM(109,I0);','R0 = PASS R0;','IF EQ JUMP gh_settings_changed;')
    for i,offset in enumerate(setting_words):
        e.line(f'R0 = DM({offset},I0);',f'R1 = DM({192+i},I0);',
               'COMP(R0,R1);','IF NE JUMP gh_settings_changed;')
    e.line('JUMP gh_settings_ready;','gh_settings_changed:')
    e.statements(SETTINGS)
    for i,offset in enumerate(setting_words):
        e.line(f'R0 = DM({offset},I0);',f'DM({192+i},I0) = R0;')
    e.line('R0 = 1;','DM(109,I0) = R0;','gh_settings_ready:',
           'R0 = DM(5,I0);','F0 = FLOAT R0;');e.store('width')
    e.statements(SAMPLE[SAMPLE.index('sidechain ='):SAMPLE.index('audio0 =')])
    e.statements('spread_inverse = 1.0/(1.0+depth) if volume_spread else 1.0')
    # C callbacks capture edges and the mode at delivery, including pulses
    # entirely between blocks. Reinterpreting raw levels here would invent a
    # manual dip if the swell mode changed after an Aux rising edge.
    for name, offset in (('pending_aux',state.PENDING_AUX),('pending_enable',state.PENDING_ENABLE)):
        e.line(f'R0 = DM({offset},I0);','F0 = FLOAT R0;');e.store(name)
    e.line('R0 = 0;','DM(6,I0) = R0;','DM(7,I0) = R0;')
    e.statements('''
if pending_enable:
    ramp_phase = 0.0
if pending_aux:
    manual_dip0 = 1.0
    manual_dip1 = 1.0
''')
    e.line('R0 = 0.0;');e.store('frame')
    e.line('gh_sample:','F0 = DM(0,I4);');e.store('raw_left')
    e.line('R0 = DM(5,I0);','R0 = R0 - 1;','IF EQ JUMP gh_mono_input;','F0 = DM(16,I4);','JUMP gh_input_ready;','gh_mono_input:');e.load('raw_left')
    e.line('gh_input_ready:');e.store('raw_right')
    e.statements(SAMPLE[:SAMPLE.index('sidechain =')]+SAMPLE[SAMPLE.index('audio0 ='):])
    for i in range(6):
        e.statements(f'''
target = k0{i}
if t30 != 0:
    automation_range = k3{i}
    target = clamp(target+automation_range*(2.0*ramp-1.0)) if t31 == 2 else target*(1.0-automation_range)+ramp*(target-target*(1.0-automation_range))
smooth{i} = target+0.997399221233823*(smooth{i}-target)
''')
    e.statements(CONTROL)
    # Both stereo detectors retain independent filter histories. A native
    # mono instance has no second program/key input or observable second state;
    # its duplicate detector is identical for every routing setting.
    for ch in range(2):
        if ch:e.line('R0 = DM(5,I0);','R0 = R0 - 1;','IF EQ JUMP gh_mono_detector;')
        e.line('R0 = I0;',f'R1 = {state.CHANNEL_BASE+state.CHANNEL_STRIDE*ch};','R0 = R0 + R1;','I6 = R0;')
        e.statements(f'detector = detector{ch}');e.statements(SENSE);e.load('sensed');e.store(f'sensed{ch}')
    e.line('JUMP gh_detectors_ready;','gh_mono_detector:');e.load('sensed0');e.store('sensed1')
    e.line('gh_detectors_ready:')
    e.statements('''
if not independent:
    sensed0 = max(sensed0,sensed1)
    sensed1 = sensed0
ch = 0.0
''')
    e.line('R0 = I0;','R1 = 128;','R0 = R0 + R1;','I6 = R0;','gh_channel:')
    e.statements('''
sensed = sensed0 if ch == 0.0 else sensed1
audio = audio0 if ch == 0.0 else audio1
volume_motion = volume_motion0 if ch == 0.0 else volume_motion1
eq_motion = eq_motion0 if ch == 0.0 else eq_motion1
pan_motion = pan_motion0 if ch == 0.0 else pan_motion1
''')
    e.statements(CHANNEL_BODY)
    e.statements('''
if ch == 0.0:
    output0 = y
else:
    output1 = y
ch = ch+1.0
''')
    e.load('ch');e.line('R1 = DM(5,I0);','F1 = FLOAT R1;','COMP(F0,F1);','IF GE JUMP gh_channels_done;','MODIFY(I6,32);','JUMP gh_channel;','gh_channels_done:')
    e.statements('''
bypass_mix = enable+0.997399221233823*(bypass_mix-enable)
if abs(bypass_mix-enable) < 0.00005:
    bypass_mix = enable
result0 = audio0+bypass_mix*(output0-audio0)
result1 = audio1+bypass_mix*(output1-audio1)
''')
    e.load('result0');e.line('DM(0,I5) = F0;','R0 = DM(5,I0);','R0 = R0 - 1;','IF EQ JUMP gh_output_done;');e.load('result1');e.line('DM(16,I5) = F0;','gh_output_done:','MODIFY(I4,1);','MODIFY(I5,1);')
    e.statements('frame = frame+1.0')
    e.load('frame');e.line('F1 = 16.0;','COMP(F0,F1);','IF LT JUMP gh_sample;')
    for i in range(6):e.line(f'DM({64+i},I0) = F{6+i};')
    for j,reg in reversed(list(enumerate(('ASTATX','ASTATY','STKYX','STKYY','I4','L4','I5','L5','I6','L6')))):
        e.line(f'R0 = DM({417+j},I0);',f'{reg} = R0;')
    for r in range(16):e.line(f'R{r} = DM({400+r},I0);')
    e.line('MODE1 = DM(416,I0);','NOP;','RTS;')
    e.line(MATH_ASM.read_text())
    return '\n'.join(e.lines)+'\n'


@lru_cache(None)
def assemble(base=0xe3000):
    if type(base) is not int or base<0 or base%2: raise ValueError('Glasshouse PM base must be nonnegative and even')
    return sasm.assemble(source(base),'glasshouse_generated.asm')


def instructions():
    return sum(len(s.words) for s in assemble()[0] if s.kind=='pm')


class Audio:
    """Native planar callback harness: all processing runs encoded instructions."""
    def __init__(self,channels=2,state_address=0xb3000,base=0xe3000,sim=None):
        if channels not in (1,2):raise ValueError('Glasshouse width must be1or2')
        self.channels,self.state,self.base=channels,state_address,base
        self.sim=sim or ssim.Sim();self.sim.strict_cbufen=True
        sections,self.symbols=assemble(base);self.sim.load(sections)
        for i in range(STATE_WORDS):self.sim.wr(self.state+i,0)
        self.sim.wr(self.state,16);self.sim.wr(self.state+2,channels);self.sim.wr(self.state+CHANNELS,channels)
        self.settings()
        self.params(enable=True)
    def settings(self,knobs=None,toggles=None):
        knobs=state.KNOB_DEFAULTS if knobs is None else knobs
        toggles=state.TOGGLE_DEFAULTS if toggles is None else toggles
        for p in range(4):
            for i in range(6):self.sim.wr(self.state+state.knob(p,i),ssim.f2b(knobs[p][i]))
            for i in range(3):self.sim.wr(self.state+state.toggle(p,i),int(toggles[p][i]))
    def params(self,**values):
        aliases={'sensitivity':'k00','dynamics':'k01','wet':'k02','attack':'k03','eq':'k04','dry':'k05'}
        for name,value in values.items():
            name=aliases.get(name,name)
            offset,integer=PARAMS[name]
            word=int(value) if integer else ssim.f2b(value)
            old=self.sim.rd(self.state+offset)
            if self.sim.rd(self.state+INITIALIZED) and not old and word:
                if offset==state.ENABLE:
                    self.sim.wr(self.state+state.PENDING_ENABLE,1)
                elif offset==state.AUX and self.sim.rd(self.state+state.toggle(2,1))==1:
                    self.sim.wr(self.state+state.PENDING_AUX,1)
            self.sim.wr(self.state+offset,word)
    def block(self,samples=None,inplace=False):
        samples=([0.]*16 if self.channels==1 else [(0.,0.)]*16) if samples is None else samples
        if len(samples)!=16:raise ValueError('native Glasshouse blocks contain16frames')
        src,dst=0xb8000,0xb8000 if inplace else 0xb8100
        for i,frame in enumerate(samples):
            for ch,v in enumerate((frame,) if self.channels==1 else frame):self.sim.wr(src+16*ch+i,ssim.f2b(v))
        for code,value in ((0x10,self.state),(0x11,src),(0x12,dst)):self.sim.set(code,value)
        self.sim.call(self.symbols[ENTRY],limit=1_000_000)
        if self.channels==1:return [ssim.b2f(self.sim.rd(dst+i)) for i in range(16)]
        return [(ssim.b2f(self.sim.rd(dst+i)),ssim.b2f(self.sim.rd(dst+16+i))) for i in range(16)]

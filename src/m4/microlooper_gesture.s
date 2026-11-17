@ Micro-looper switch gestures, independent of the stock footswitch handler.
@ The future M4 adapter must route one assigned switch here, suppress that
@ switch's ordinary bypass/long-press actions, and poll while it is held.
@ This module does not install a hook or call firmware functions.
@
@ microlooper_gesture_update(r0 state, r1 pressed, r2 now_us, r3 playing)
@   state: caller-owned, 4-byte-aligned 8 bytes, initially zero or reset:
@          +0 flags (bit0 down, bit1 hold recognized), +4 press timestamp.
@   pressed/playing: zero false, nonzero true. now_us: wrapping uint32 us.
@   returns r0 flags: bit0 TAP pulse, bit1 OVERDUB level; all others zero.
@   TAP on release before 400000us tells the caller to toggle Listen/Play.
@   At/after 400000us a hold suppresses TAP, including when the first poll
@   after the press is the release. OVERDUB is true only while held and
@   currently playing. A hold while listening never captures on release.
@   Repeated levels are idempotent. Poll intervals/presses must be shorter
@   than one uint32 timestamp period (~71 minutes) until a hold is recognized;
@   the hold then stays latched until release, even across another wrap.
@   Registers r0-r3, r12 and flags are clobbered; r4-r11/SP are preserved.
@
@ microlooper_gesture_reset(r0 state) -> r0=0, clears the eight state bytes.
@ Use reset on graph removal/rebind and explicitly clear the DSP Overdub
@ level there; do not synthesize a release (which could emit TAP).
@ State is per caller/assignment, with no global or singleton storage.
.syntax unified
.thumb
.equ MICROLOOPER_GESTURE_DOWN, 1
.equ MICROLOOPER_GESTURE_HELD, 2
.equ MICROLOOPER_GESTURE_HOLD_US, 400000

.thumb_func
microlooper_gesture_reset:
    movs r1, #0
    str r1, [r0]
    str r1, [r0, #4]
    movs r0, #0
    bx lr

.thumb_func
microlooper_gesture_update:
    push {r4, lr}
    mov r4, r0
    ldr r12, [r4]
    tst r12, #MICROLOOPER_GESTURE_DOWN
    bne .Lmicrolooper_down
    cmp r1, #0
    beq .Lmicrolooper_none
    movs r0, #MICROLOOPER_GESTURE_DOWN
    str r0, [r4]
    str r2, [r4, #4]
    b .Lmicrolooper_none

.Lmicrolooper_down:
    tst r12, #MICROLOOPER_GESTURE_HELD
    bne .Lmicrolooper_hold
    ldr r0, [r4, #4]
    subs r2, r2, r0
    movw r0, #(MICROLOOPER_GESTURE_HOLD_US & 0xffff)
    movt r0, #(MICROLOOPER_GESTURE_HOLD_US >> 16)
    cmp r2, r0
    bhs .Lmicrolooper_hold
    cmp r1, #0
    bne .Lmicrolooper_none
    movs r0, #0
    str r0, [r4]
    movs r0, #1                     @ one tap pulse, on this release only
    b .Lmicrolooper_out

.Lmicrolooper_hold:
    cmp r1, #0
    beq .Lmicrolooper_release_hold
    movs r0, #(MICROLOOPER_GESTURE_DOWN | MICROLOOPER_GESTURE_HELD)
    str r0, [r4]
    cmp r3, #0
    beq .Lmicrolooper_none
    movs r0, #2                     @ overdub is a level, not a repeated action
    b .Lmicrolooper_out
.Lmicrolooper_release_hold:
    movs r0, #0
    str r0, [r4]
.Lmicrolooper_none:
    movs r0, #0
.Lmicrolooper_out:
    pop {r4, pc}

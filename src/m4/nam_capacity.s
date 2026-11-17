@ Five-argument NAM resource admission wrapper, installed by the Micro profile.
@ Same ABI as stock0x28dfae0c(r0 context,r1 preset,r2 replaced,r3 candidate,
@                         stack0 out_bool*), returning native status unchanged.
@ Intended for guarded native call sites, leaving the original entry intact.
@ nam_capacity.inc is explicit for this image: compiled NAM profile capacity
@ and its actual name index. No runtime flags, warnings or Micro instance rule.
@
@ Native cost/error/refund check runs first. Only an admissible, nonempty NAM
@ candidate gets an additional pool-capacity check. Count exactly the objects
@ considered by native0x28dfa31c: index0..4 below byte[preset+0xac4], always5..8;
@ object preset+0xaf0+index*0x9f4, in-use bit0 at+0x24, primary name at+0x54.
@ Exclude r2 only if that exact object would be counted: replacement refunds
@ its occupied slot. Inactive or excluded objects grant no refund.
@ The meaning of ac4 beyond this observed eligibility rule is not assumed.
.syntax unified
.thumb
.include "nam_capacity.inc"

.thumb_func
nam_capacity_admit:
    push {r4-r11, lr}
    sub sp, #12                    @ aligned outgoing stack argument
    mov r4, r1
    mov r5, r2
    mov r6, r3
    ldr r7, [sp, #48]              @ original fifth argument
    str r7, [sp]
    ldr r12, =NC_NATIVE_BUDGET
    blx r12
    mov r8, r0
    cmp r0, #0
    blt .Lnc_out                   @ even native out_bool-on-error stays intact
    ldrb r0, [r7]
    cbz r0, .Lnc_out               @ never turn a native refusal into admission
    ldrb r0, [r6]
    cbz r0, .Lnc_out               @ native kind0 is empty/removal, not a NAM
    ldr r9, =NC_NAM_NAME_INDEX
    ldr r0, [r6, #4]
    cmp r0, r9
    bne .Lnc_out
    addw r6, r4, #0xaf0
    mov.w r10, #0
    mov.w r11, #0
.Lnc_scan:
    cmp r10, #5
    bhs .Lnc_eligible
    ldrb.w r0, [r4, #0xac4]
    cmp r10, r0
    bhs .Lnc_next
.Lnc_eligible:
    ldr r0, [r6, #0x24]
    tst r0, #1
    beq .Lnc_next
    cmp r6, r5
    beq .Lnc_next                  @ refund only a counted replacement object
    ldr r0, [r6, #0x54]
    cmp r0, r9
    it eq
    addeq.w r11, r11, #1
.Lnc_next:
    addw r6, r6, #0x9f4
    add.w r10, r10, #1
    cmp r10, #9
    blo .Lnc_scan
    cmp r11, #NC_CAPACITY          @ adding this NAM needs one more pool slot
    blo .Lnc_out
    movs r0, #0
    strb r0, [r7]                  @ ordinary browser admissible=false
.Lnc_out:
    mov r0, r8
    add sp, #12
    pop {r4-r11, pc}
    .ltorg

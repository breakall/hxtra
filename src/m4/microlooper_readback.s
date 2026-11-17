@ Diagnostic only. Explicit builder installs/registers; no public feature flag.
@ Frame219 tag,220 sequence,221 length16,222..237 payload,238 end sequence.
@ Source invalidates BOTH guards odd before payload; commits end then begin.
@ RX normalizes halfword-swapped words, snapshots privately and never blocks.
@ USB result96 little-endian bytes:8u32 {tag,96,valid,source_seq,received_us,
@ now_us,age_us,reserved0}, then16u32 context. Invalid record zeros all but
@ tag,length,now_us. Only forward source progress refreshes received_us.
.syntax unified
.thumb
.include "microlooper_readback.inc"
.equ CLOCK, 0x28da6459
.equ CACHE_END, 80
.equ REPLY_BYTES, 96
.equ COPY_TRIES, 3
.equ SERVICE, 6
.equ REGISTER, 0x28e165f1
.equ NO_PARAMS, 0x28e19205
.equ WRITER, 0x28e157c9
.equ PREFIX_LEN, 0x28e157ed
.equ PREFIX, 0x28e15811
.equ PREFIX_RESET, 0x28e15835
.equ REPLY_HEAD, 0x28e15879
.equ LOCK, 0x28e24c01
.equ UNLOCK, 0x28e24bb1

.thumb_func
mlr_frame:                         @ (context,r1 RX frame); preserves all registers
    push {r0-r12, lr}
    sub sp, #64
    mov r4, r1
    ldr r0, [r4]
    ldr r1, =0xf00dface
    cmp r0, r1
    bne .Lmlr_frame_out
    ldr.w r0, [r4, #1020]
    ldr r1, =0xecafd00f
    cmp r0, r1
    bne .Lmlr_frame_out
    ldr.w r0, [r4, #876]
    ror.w r0, r0, #16
    ldr r1, =MLR_TAG
    cmp r0, r1
    bne .Lmlr_frame_out
    ldr.w r0, [r4, #884]
    ror.w r0, r0, #16
    cmp r0, #16
    bne .Lmlr_frame_out
    ldr.w r6, [r4, #880]
    ror.w r6, r6, #16
    tst r6, #1
    bne .Lmlr_frame_out
    ldr.w r0, [r4, #952]
    ror.w r0, r0, #16
    cmp r0, r6
    bne .Lmlr_frame_out
    dmb
    addw r7, r4, #888
    mov r3, sp
    movs r2, #16
mlr_frame_copy:
    ldr r0, [r7], #4
    ror.w r0, r0, #16
    str r0, [r3], #4
    subs r2, #1
    bne mlr_frame_copy
    ldr r0, [sp]
    ldr r1, =MLR_CONTEXT_MAGIC
    cmp r0, r1
    bne .Lmlr_frame_out
    dmb
mlr_frame_validate:
    ldr.w r0, [r4, #880]
    ror.w r0, r0, #16
    cmp r0, r6
    bne .Lmlr_frame_out
    ldr.w r0, [r4, #952]
    ror.w r0, r0, #16
    cmp r0, r6
    bne .Lmlr_frame_out
    adr.w r5, mlr_cache
    ldr r0, [r5, #12]
    cbz r0, .Lmlr_frame_new
    ldr r0, [r5, #4]
    subs r0, r6, r0                 @ modular delta; reject old/duplicate/ambiguous
    cmp r0, #0
    ble .Lmlr_frame_out             @ positive signed delta accepts uint32 wrap
.Lmlr_frame_new:
    ldr r3, =CLOCK
    blx r3
    mov r8, r0
    ldr r7, [r5]
    adds r7, #1
mlr_cache_invalidate:
    str r7, [r5]
    str r7, [r5, #CACHE_END]
    dmb
    str r6, [r5, #4]
    str r8, [r5, #8]
    movs r0, #1
    str r0, [r5, #12]
    mov r1, sp
    add r3, r5, #16
    movs r2, #16
mlr_cache_publish_copy:
    ldr r0, [r1], #4
    str r0, [r3], #4
    subs r2, #1
    bne mlr_cache_publish_copy
    dmb
    adds r7, #1
    str r7, [r5, #CACHE_END]
    dmb
    str r7, [r5]
    dmb
.Lmlr_frame_out:
    add sp, #64
    pop {r0-r12, pc}
    .ltorg

.thumb_func
mlr_copy_reply:                    @ (out96bytes) ->valid0/1; bounded, private copy
    push {r4-r8, lr}
    mov r4, r0
    adr.w r5, mlr_cache
    movs r6, #COPY_TRIES
mlr_reply_try:
    ldr r7, [r5]
    tst r7, #1
    bne .Lmlr_reply_retry
    dmb
    ldr r0, [r5, #12]
    cbz r0, .Lmlr_reply_invalid
    ldr r0, [r5, #4]
    str r0, [r4, #12]
    ldr r0, [r5, #8]
    str r0, [r4, #16]
    add r1, r5, #16
    add r3, r4, #32
    movs r2, #16
mlr_reply_copy:
    ldr r0, [r1], #4
    str r0, [r3], #4
    subs r2, #1
    bne mlr_reply_copy
    dmb
mlr_reply_validate:
    ldr r0, [r5, #CACHE_END]
    cmp r0, r7
    bne .Lmlr_reply_retry
    ldr r0, [r5]
    cmp r0, r7
    bne .Lmlr_reply_retry
    movs r0, #1
    str r0, [r4, #8]
    b .Lmlr_reply_clock
.Lmlr_reply_retry:
    subs r6, #1
    bne mlr_reply_try
.Lmlr_reply_invalid:
    movs r0, #0
    add r1, r4, #8
    movs r2, #22
.Lmlr_reply_zero:
    str r0, [r1], #4
    subs r2, #1
    bne .Lmlr_reply_zero
.Lmlr_reply_clock:
    ldr r3, =CLOCK
    blx r3
    str r0, [r4, #20]
    ldr r1, [r4, #8]
    cbz r1, .Lmlr_reply_header
    ldr r1, [r4, #16]
    subs r0, r0, r1
    str r0, [r4, #24]
.Lmlr_reply_header:
    ldr r0, =MLR_TAG
    str r0, [r4]
    movs r0, #REPLY_BYTES
    str r0, [r4, #4]
    movs r0, #0
    str r0, [r4, #28]
    ldr r0, [r4, #8]
    pop {r4-r8, pc}
    .ltorg

.thumb_func
mlr_register:                      @ after native editor registration
    push {r4, lr}
    sub sp, #16
    adr.w r0, mlr_cmd
    orr r0, r0, #1
    ldr r1, =NO_PARAMS
    movs r2, #0
    str r0, [sp, #4]
    str r1, [sp, #8]
    str r2, [sp, #12]
    movs r0, #MLR_CMD
    add r1, sp, #4
    ldr r3, =REGISTER
    blx r3
    add sp, #16
    pop {r4, pc}
    .ltorg

.thumb_func
mlr_cmd:                           @ (editor stream, request) ->native stream status
    push {r4-r11, lr}
    sub sp, #116                   @ header8,bin header8,private reply96,scratch4
    mov r4, r0
    ldrh r5, [r1, #12]
    add r10, sp, #16
    mov r0, r10
    bl mlr_copy_reply
    movs r0, #SERVICE
    ldr r3, =WRITER
    blx r3
    mov r8, r0
    movs r0, #SERVICE
    ldr r3, =PREFIX_LEN
    blx r3
    mov r6, r0
    movs r0, #SERVICE
    ldr r3, =PREFIX
    blx r3
    mov r7, r0
    movs r0, #SERVICE
    ldr r3, =PREFIX_RESET
    blx r3
    mov r0, r8
    mov r1, r5
    movs r2, #0
    ldr r3, =REPLY_HEAD
    blx r3
    movs r0, #0xc6                @ MessagePack bin32, big-endian length96
    strb r0, [sp, #8]
    movs r0, #0
    strb r0, [sp, #9]
    strb r0, [sp, #10]
    strb r0, [sp, #11]
    movs r0, #REPLY_BYTES
    strb r0, [sp, #12]
    ldr r0, [r8]
    ldr r3, [r8, #4]
    add r1, sp, #8
    movs r2, #5
    blx r3
    mov r11, r0
    cmp r0, #0
    blt .Lmlr_cmd_out
    sub r0, r4, #8
    ldr r3, =LOCK
    blx r3
    movs r0, #0
    strh r0, [sp]
    movs r0, #SERVICE
    strh r0, [sp, #2]
    ldr r0, [r6]
    adds r0, #REPLY_BYTES
    str r0, [sp, #4]
    mov r0, r4
    mov r1, sp
    movs r2, #8
    bl .Lmlr_write
    cmp r11, #0
    blt .Lmlr_cmd_unlock
    mov r0, r4
    mov r1, r7
    ldr r2, [r6]
    bl .Lmlr_write
    cmp r11, #0
    blt .Lmlr_cmd_unlock
    mov r0, r4
    mov r1, r10
    movs r2, #REPLY_BYTES
    bl .Lmlr_write
    cmp r11, #0
    blt .Lmlr_cmd_unlock
    mov r0, r4
    movs r1, #0
    ldr r3, [r4]
    ldr r3, [r3, #12]
    blx r3
    mov r11, r0
.Lmlr_cmd_unlock:
    sub r0, r4, #8
    ldr r3, =UNLOCK
    blx r3
.Lmlr_cmd_out:
    mov r0, r11
    add sp, #116
    pop {r4-r11, pc}
.Lmlr_write:
    ldr r3, [r4]
    ldr r3, [r3, #4]
    mov r12, lr
    push {r12, lr}
    blx r3
    mov r11, r0
    pop {r12, pc}
    .ltorg

.balign 4
mlr_cache:
    .space 84                      @ begin,source_seq,received_us,valid,payload16,end

@ Stateful micro-looper gesture adapter and verified native routing helpers.
@ Explicit development installer composes input, polling and native lifetimes.
@
@ microlooper_binding_update(r0 state, r1 pressed, r2 now_us, r3 binding)
@ state: caller-owned, aligned32 bytes, initially zero:
@   +0/+4 gesture flags/time; +8 block handle; +12 generation;
@   +16 desired Play; +20 desired Overdub; +24 dirty bits1Play/2Overdub;
@   +28 initialized. State is per block/assignment, never a singleton.
@ binding: immutable20 bytes {context, write_fn, block, generation, model_id}.
@ write_fn(context, block, parameter_slot, bool_value) returns0 on success,
@ nonzero on failure. Slots6/7 are Play/Overdub (not DSP PIDs10/11).
@ Returns bit0 claimed if model380, bit2 if write failed; non-looper returns0
@ without touching state. dirty desired values retry on subsequent polls;
@ failed Play prevents an Overdub write from overtaking it.
@ New binding resets gesture/desired states and sends Listen/OverdubOff before
@ it can receive a later tap. A held input is inhibited until release at rebind;
@ it cannot turn an old release into capture. Caller must supply a new generation
@ on graph replacement even if the allocator reuses the block handle.
@
@ microlooper_binding_cancel(r0 state,r1 binding): send OverdubOff and clear
@ state for a matching binding; retryable failure leaves state intact. A stale
@ binding is ignored. Call BEFORE losing valid native ownership of the block.
@ microlooper_binding_reset(r0 state) clears local32 bytes WITHOUT touching DSP.
@ Native caller still must install selective bypass, suppress longpress, poll while
@ down, pass a proven writer, keep listening block enabled and filter snapshot
@ parameter restoration. This module does not prove any of those native seams.
.syntax unified
.thumb
.include "microlooper_gesture.s"
.equ ML_MODEL, 380
.equ ML_PLAY, 6
.equ ML_OVERDUB, 7

.thumb_func
microlooper_binding_reset:
    movs r1, #0
    str r1, [r0]
    str r1, [r0, #4]
    str r1, [r0, #8]
    str r1, [r0, #12]
    str r1, [r0, #16]
    str r1, [r0, #20]
    str r1, [r0, #24]
    str r1, [r0, #28]
    movs r0, #0
    bx lr

.thumb_func
microlooper_binding_update:
    push {r4-r8, lr}
    mov r4, r0
    mov r5, r3
    ldr r0, [r5, #16]
    movw r3, #ML_MODEL
    cmp r0, r3
    bne .Lml_unclaimed
    mov r6, r1
    mov r7, r2
    ldr r0, [r4, #28]
    cmp r0, #0
    beq .Lml_bind
    ldr r0, [r5, #8]
    ldr r1, [r4, #8]
    cmp r0, r1
    bne .Lml_bind
    ldr r0, [r5, #12]
    ldr r1, [r4, #12]
    cmp r0, r1
    beq .Lml_poll
.Lml_bind:
    mov r0, r4
    bl microlooper_binding_reset
    ldr r0, [r5, #8]
    str r0, [r4, #8]
    ldr r0, [r5, #12]
    str r0, [r4, #12]
    movs r0, #3
    str r0, [r4, #24]
    movs r0, #1
    str r0, [r4, #28]
    cmp r6, #0
    it ne
    movne r0, #4                  @ a rebind while down must await release
    it ne
    strne r0, [r4]
.Lml_poll:
    ldr r0, [r4]
    tst r0, #4
    beq .Lml_poll_gesture
    cmp r6, #0
    it eq
    moveq r0, #0
    it eq
    streq r0, [r4]
    movs r8, #0                  @ suspended input cannot capture or overdub
    b .Lml_od
.Lml_poll_gesture:
    mov r0, r4
    mov r1, r6
    mov r2, r7
    ldr r3, [r4, #16]
    bl microlooper_gesture_update
    mov r8, r0
    tst r8, #1
    beq .Lml_od
    ldr r0, [r4, #16]
    eor r0, r0, #1
    str r0, [r4, #16]
    ldr r0, [r4, #24]
    orr r0, r0, #1
    str r0, [r4, #24]
.Lml_od:
    ubfx r0, r8, #1, #1
    ldr r1, [r4, #20]
    cmp r0, r1
    beq .Lml_flush
    str r0, [r4, #20]
    ldr r0, [r4, #24]
    orr r0, r0, #2
    str r0, [r4, #24]
.Lml_flush:
    ldr r0, [r4, #24]
    tst r0, #1
    beq .Lml_flush_od
    ldr r0, [r5]
    ldr r1, [r5, #8]
    movs r2, #ML_PLAY
    ldr r3, [r4, #16]
    ldr r12, [r5, #4]
    blx r12
    cmp r0, #0
    bne .Lml_failed
    ldr r0, [r4, #24]
    bic r0, r0, #1
    str r0, [r4, #24]
.Lml_flush_od:
    ldr r0, [r4, #24]
    tst r0, #2
    beq .Lml_claimed
    ldr r0, [r5]
    ldr r1, [r5, #8]
    movs r2, #ML_OVERDUB
    ldr r3, [r4, #20]
    ldr r12, [r5, #4]
    blx r12
    cmp r0, #0
    bne .Lml_failed
    ldr r0, [r4, #24]
    bic r0, r0, #2
    str r0, [r4, #24]
.Lml_claimed:
    movs r0, #1
    b .Lml_out
.Lml_failed:
    movs r0, #5
    b .Lml_out
.Lml_unclaimed:
    movs r0, #0
.Lml_out:
    pop {r4-r8, pc}

@ Suspend a still-owned transport without changing Play/capture. The private
@ inhibit bit4 stays until release; failed OverdubOff remains dirty/retryable.
.thumb_func
microlooper_binding_suspend:
    push {r4-r6, lr}
    mov r4, r0
    mov r5, r1
    ldr r0, [r4, #28]
    cbz r0, .Lml_suspend_done
    movs r0, #4
    str r0, [r4]
    ldr r0, [r4, #20]
    cbz r0, .Lml_suspend_poll
    movs r0, #0
    str r0, [r4, #20]
    ldr r0, [r4, #24]
    orr r0, r0, #2
    str r0, [r4, #24]
.Lml_suspend_poll:
    mov r0, r4
    movs r1, #1
    movs r2, #0
    mov r3, r5
    bl microlooper_binding_update
.Lml_suspend_done:
    pop {r4-r6, pc}

.thumb_func
microlooper_binding_cancel:
    push {r4-r6, lr}
    mov r4, r0
    mov r5, r1
    ldr r0, [r4, #28]
    cbz r0, .Lml_cancel_none
    ldr r0, [r5, #16]
    movw r1, #ML_MODEL
    cmp r0, r1
    bne .Lml_cancel_none
    ldr r0, [r5, #8]
    ldr r1, [r4, #8]
    cmp r0, r1
    bne .Lml_cancel_none
    ldr r0, [r5, #12]
    ldr r1, [r4, #12]
    cmp r0, r1
    bne .Lml_cancel_none
    ldr r0, [r5]
    ldr r1, [r5, #8]
    movs r2, #ML_OVERDUB
    movs r3, #0
    ldr r12, [r5, #4]
    blx r12
    cbnz r0, .Lml_cancel_failed
    mov r0, r4
    bl microlooper_binding_reset
    movs r0, #1
    pop {r4-r6, pc}
.Lml_cancel_failed:
    movs r0, #5
    pop {r4-r6, pc}
.Lml_cancel_none:
    movs r0, #0
    pop {r4-r6, pc}

@ Verified outer native setter interface, stock3.80 callers at0x28dde5b2..
@ 0x28dde60c and MIDI parameter caller0x28d9b2fc..0x28d9b436.
@ This is suitable as binding.write_fn ONLY with a valid tone context and block
@ identifier, after native assignment/lifecycle routing is established.
@ (tone, block, UI slot6/7, bool) -> native status; rejects other slots.
@ Stack descriptor: selector-2(primary model), zero-based parameter index,
@ flag0 selects normal effect controls; flag1 selects native special fields.
@ Packed value: type1(bool), value at+1.
.thumb_func
microlooper_native_write:
    cmp r2, #6
    beq .Lml_native_slot
    cmp r2, #7
    beq .Lml_native_slot
    mvn r0, #2
    bx lr
.Lml_native_slot:
    push {r4, lr}
    sub sp, #24
    mov r4, r3
    movs r3, #0
    str r3, [sp]
    str r3, [sp, #4]
    str r3, [sp, #8]
    str r3, [sp, #12]
    str r3, [sp, #16]
    mvn r3, #1
    str r3, [sp]                  @ primary model selector=-2
    subs r2, #1
    str r2, [sp, #4]              @ UI slot is1-based, native index is0-based
    movs r3, #1
    strb r3, [sp, #12]            @ native bool type
    cmp r4, #0
    it ne
    movne r4, #1
    strb r4, [sp, #13]
    mov r2, sp
    add r3, sp, #12
    ldr r4, =0x28e04865
    blx r4
microlooper_native_write_return:
    add sp, #24
    pop {r4, pc}

@ (tone, assignment_node, out_block) ->1 if node is a micro-looper,0 otherwise.
@ Type1 bypass nodes keep block identifier at+0xc; next pointer is+0.
@ Node kinds observed in stock0x28dd113e's table: type1 executes block lookup
@ at0x28dd1190, type2 drives switch/controller state, type3 Command Center.
@ Read-only lookup; unknown block/model leaves out_block unchanged.
.thumb_func
microlooper_native_node_match:
    push {r4-r6, lr}
    sub sp, #56
    mov r5, r2
    ldrb r2, [r1, #9]
    cmp r2, #1
    bne .Lml_native_no_match
    ldr r4, [r1, #12]
    mov r1, r4
    movs r3, #0
    str r3, [sp]
    str r3, [sp, #4]               @ native invalid-ID path can return0 unwritten
    mov r2, sp
    ldr r3, =0x28e0fe95
    blx r3
    cmp r0, #0
    blt .Lml_native_no_match
    ldr r0, [sp, #1]
    movw r1, #ML_MODEL
    cmp r0, r1
    bne .Lml_native_no_match
    str r4, [r5]
    movs r0, #1
    b .Lml_native_match_out
.Lml_native_no_match:
    movs r0, #0
.Lml_native_match_out:
    add sp, #56
    pop {r4-r6, pc}
    .ltorg

@ Inline hook at stock0x28dd11aa, AFTER successful kind1 model-info lookup.
@ Stock bytes9df82830: ldrb.w r3,[sp,#40]. ID is unaligned word[sp+29].
@ Skip only model380's node before its latch, colour or bypass is changed.
@ Other nodes replay the displaced instruction and follow the original code.
@ Requires the original dispatch frame; never call this as an ABI function.
@ This isolated hook is tested against stock code. No feature installs it
@ until the input, polling and lifecycle paths are wired together.
.thumb_func
microlooper_native_bypass_filter:
    push {r0, r1}
    ldr r0, [sp, #37]
    movw r1, #ML_MODEL
    cmp r0, r1
    pop {r0, r1}
    beq .Lml_native_skip_bypass
    ldrb.w r3, [sp, #40]
    ldr pc, =0x28dd11af
.Lml_native_skip_bypass:
    ldr pc, =0x28dd1187
    .ltorg

@ Entry hook at stock0x28e04864, guarded push.w {r4-r9,lr}.
@ Restricts primary model380 native transport writes to our writer's actual
@ return address. No process-global allow flag or cross-thread window.
@ Other models, settings and secondary-model writes run the original setter.
@ Native0x28e08454 treats selector-3 as secondary and other selectors as primary.
@ Ignored transport writes return success0, as snapshot callers expect.
@ This covers this setter route, NOT initial graph construction or other
@ direct graph writes. Feature enablement still requires those lifecycle facts.
.thumb_func
microlooper_native_parameter_filter:
    push {r0-r7, lr}
    sub sp, #60
    adr.w r4, microlooper_native_write_return
    orr r4, r4, #1
    cmp lr, r4
    beq .Lml_parameter_pass
    ldr r4, [r2, #4]
    cmp r4, #5
    beq .Lml_parameter_transport
    cmp r4, #6
    bne .Lml_parameter_pass
.Lml_parameter_transport:
    ldr r4, [r2]
    cmn r4, #3
    beq .Lml_parameter_pass
    movs r4, #0
    str r4, [sp]
    str r4, [sp, #4]               @ unknown block may return0 without an info record
    mov r2, sp
    ldr r3, =0x28e0fe95
    blx r3
    cmp r0, #0
    blt .Lml_parameter_pass
    ldr r4, [sp, #1]
    movw r5, #ML_MODEL
    cmp r4, r5
    bne .Lml_parameter_pass
    add sp, #60
    pop {r0-r7, lr}
    movs r0, #0
    bx lr
.Lml_parameter_pass:
    add sp, #60
    pop {r0-r7, lr}
    push.w {r4-r9, lr}             @ displaced stock entry
    ldr pc, =0x28e04869
    .ltorg

@ (assignment_manager, fs0..4, out_block_ids, capacity_words) -> total kind1
@ assignments. Copies at most capacity IDs; no native node pointer escapes.
@ Native0x28dd71c4/0x28dd71e4 establish manager+4 mutex and sentinel layout.
@ Holds only that mutex while traversing; never performs a DSP lookup/write
@ inside it. Caller must still establish graph generation after this snapshot.
.thumb_func
microlooper_native_assignment_ids:
    cmp r1, #5
    blo .Lml_ids_valid
    movs r0, #0
    bx lr
.Lml_ids_valid:
    push {r4-r8, lr}
    mov r4, r0
    mov r5, r2
    mov r6, r3
    adds r1, #1
    add.w r7, r4, r1, lsl #5
    adds r0, r4, #4
    ldr r3, =0x28e24c01
    blx r3
    ldr r2, [r7]
    movs r8, #0
.Lml_ids_scan:
    cmp r2, r7
    beq .Lml_ids_done
    ldrb r3, [r2, #9]
    cmp r3, #1
    bne .Lml_ids_next
    cmp r8, r6
    bhs .Lml_ids_count
    ldr r3, [r2, #12]
    str.w r3, [r5, r8, lsl #2]
.Lml_ids_count:
    add.w r8, r8, #1
.Lml_ids_next:
    ldr r2, [r2]
    b .Lml_ids_scan
.Lml_ids_done:
    adds r0, r4, #4
    ldr r3, =0x28e24bb1
    blx r3
    mov r0, r8
    pop {r4-r8, pc}
    .ltorg

@ Explicit per-binding event composition, NOT an installed event hook.
@ (event, stomp_obj, route) ->0 unclaimed,1 claimed,5 claimed/write retry.
@ route20 bytes: {state*, binding*, fs0..4, stock_handler, lp_event_handler}.
@ Caller must select a live eligible Stomp assignment and initialize its binding
@ before events. The binding's generation/lifetime is still caller-owned.
@ Unrelated events go to lp_event(event,obj,stock_handler), preserving its ABI.
@ Looper PRESS/RELEASE update transport and run stock directly: the selective
@ bypass filter excludes only this block while other assigned blocks still act.
@ Looper HOLD5 is consumed, so neither native nor custom1s alternate action runs.
@ CLICK3 reaches stock directly and cannot replay a held-back long_press press.
.thumb_func
microlooper_binding_event:
    push {r4-r8, lr}
    mov r4, r0
    mov r5, r1
    mov r6, r2
    movs r8, #0
    ldrb r0, [r4]
    cmp r0, #1
    bne .Lml_event_lp
    ldrb r0, [r4, #1]
    subs r0, #12
    cmp r0, #5
    bhs .Lml_event_lp
    ldr r1, [r6, #8]
    cmp r0, r1
    bne .Lml_event_lp
    ldr r3, [r6, #4]
    ldr r0, [r3, #16]
    movw r1, #ML_MODEL
    cmp r0, r1
    bne .Lml_event_lp
    ldr r7, [r4, #4]
    movs r8, #1
    cmp r7, #1
    beq .Lml_event_update
    cmp r7, #2
    beq .Lml_event_update
    cmp r7, #5
    bne .Lml_event_stock
.Lml_event_update:
    ldr r3, =0x28da6459
    blx r3
    mov r2, r0
    movs r1, #1
    cmp r7, #2
    it eq
    moveq r1, #0
    ldr r0, [r6]
    ldr r3, [r6, #4]
    bl microlooper_binding_update
    mov r8, r0
    cmp r7, #5
    beq .Lml_event_out
.Lml_event_stock:
    ldr r3, [r6, #12]
    mov r0, r4
    mov r1, r5
    blx r3
    b .Lml_event_out
.Lml_event_lp:
    mov r0, r4
    mov r1, r5
    ldr r2, [r6, #12]
    ldr r3, [r6, #16]
    blx r3
.Lml_event_out:
    mov r0, r8
    pop {r4-r8, pc}
    .ltorg

@ (class3event, stomp_obj, route) -> binding_update result, or0 for other class.
@ Uses the native handler's physical pressed byte and microsecond clock. The
@ caller must remove/cancel routes as eligibility or generation changes; this
@ helper does not infer lifetime from a reused block ID or node address.
.thumb_func
microlooper_binding_tick:
    push {r4-r6, lr}
    mov r4, r2
    mov r5, r1
    ldrb r0, [r0]
    cmp r0, #3
    bne .Lml_tick_unclaimed
    ldr r6, [r4, #8]
    cmp r6, #5
    bhs .Lml_tick_unclaimed
    ldr r3, =0x28da6459
    blx r3
    mov r2, r0
    add r1, r5, r6
    ldrb r1, [r1, #0x78]
    ldr r0, [r4]
    ldr r3, [r4, #4]
    bl microlooper_binding_update
    pop {r4-r6, pc}
.Lml_tick_unclaimed:
    movs r0, #0
    pop {r4-r6, pc}
    .ltorg

@ Installed controller. Forty80-byte records cover native5x8 assignment
@ storage; each unique block owns ONE transport, combining its switch mask.
@ Record: state32, binding20, switchmask+52, nativeblockobject+56, seenmask+60,
@ owned runtime link+64, twelve reserved bytes. Native init/destruction establish
@ epochs; retained native moves can change grid IDs/object addresses.
@ All controller access is serialized by the native graph mutex. Assignment
@ IDs are copied under their own mutex in native graph-before-assignment order.
.equ ML_ROUTE_COUNT, 40
.equ ML_ROUTE_SIZE, 80             @ +64 owned native runtime link; remaining12 reserved

.thumb_func
microlooper_controller_lock:
    ldr r3, =0x28449e78
    ldr r3, [r3]
    cbz r3, .Lml_lock_out
    movs r0, #0
    ldr r3, =0x28e07845
    bx r3
.Lml_lock_out:
    bx lr
.thumb_func
microlooper_controller_unlock:
    ldr r3, =0x28449e78
    ldr r3, [r3]
    cbz r3, .Lml_unlock_out
    movs r0, #0
    ldr r3, =0x28e0785d
    bx r3
.Lml_unlock_out:
    bx lr
    .ltorg

@ Input context is the UI listener, not the assignment manager. Resolve the
@ manager through the same getter used by the native bypass dispatcher.
@ Hold graph then assignment mutex through discovery and writes; the copied-ID
@ accessor recursively takes the manager mutex. Lifecycle needs only graph.
.thumb_func
microlooper_controller_input_lock:
    push {r4, lr}
    bl microlooper_controller_lock
    ldr r3, =0x28d96085
    blx r3
    adds r0, #4
    ldr r3, =0x28e24c01
    blx r3
    pop {r4, pc}
.thumb_func
microlooper_controller_input_unlock:
    push {r4, lr}
    ldr r3, =0x28d96085
    blx r3
    adds r0, #4
    ldr r3, =0x28e24bb1
    blx r3
    bl microlooper_controller_unlock
    pop {r4, pc}
    .ltorg

@ Under graph lock, ordinary grid ID -> native block object or0. The slot
@ record/node-table mapping is the same one native0x28e0904c and dsp_meter use.
.thumb_func
microlooper_controller_object:
    subs r0, #1
    cmp r0, #7
    bls .Lml_object_slot
    subs r0, #10
    cmp r0, #7
    bhi .Lml_object_none
    adds r0, #8
.Lml_object_slot:
    ldr r1, =0x28449e78
    ldr r1, [r1]
    cbz r1, .Lml_object_none
    movs r2, #0x54
    mla r0, r0, r2, r1
    ldr r0, [r0, #0x14]
    cmp r0, #0x4b
    bhi .Lml_object_none
    add.w r1, r1, #0x4400
    ldr r1, [r1]
    cbz r1, .Lml_object_none
    add.w r1, r1, r0, lsl #2
    ldr r0, [r1, #0x24]
    cbz r0, .Lml_object_none
    ldrb r1, [r0, #5]
    cmp r1, #1
    bne .Lml_object_none
    ldr r1, [r0, #0x24]
    and r1, r1, #3
    cmp r1, #3
    bne .Lml_object_none
    ldr.w r1, [r0, #0x9f0]
    cmp r1, #0
    bne .Lml_object_out
.Lml_object_none:
    movs r0, #0
.Lml_object_out:
    bx lr
    .ltorg

@ (stomp_obj)->physical pressed switch mask. Native five pressed bytes+0x78.
.thumb_func
microlooper_controller_pressed:
    movs r1, #0
    movs r2, #0
.Lml_pressed_loop:
    add r3, r0, r2
    ldrb r3, [r3, #0x78]
    cbz r3, .Lml_pressed_next
    movs r3, #1
    lsl.w r3, r3, r2
    orrs r1, r3
.Lml_pressed_next:
    adds r2, #1
    cmp r2, #5
    bne .Lml_pressed_loop
    mov r0, r1
    bx lr

@ (stomp_obj) refresh eligible routes, retire disappeared bindings, initialize
@ new bindings BEFORE a key's new pressed level is applied. Caller owns lock.
.thumb_func
microlooper_controller_refresh:
    push {r4-r11, lr}
    sub sp, #100                  @ info56, IDs32, setting8, padding4
    mov r4, r0
    bl microlooper_controller_pressed
    mov r11, r0
    adr.w r5, microlooper_controller_routes
    movs r6, #ML_ROUTE_COUNT
    movs r0, #0
.Lml_refresh_clear:
    str r0, [r5, #60]
    adds r5, #ML_ROUTE_SIZE
    subs r6, #1
    bne .Lml_refresh_clear
    movs r0, #21
    add r1, sp, #88
    ldr r3, =0x28e1f845
    blx r3
    cmp r0, #0
    blt .Lml_refresh_retire
    ldr r0, [sp, #92]
    subs r0, #2
    cmp r0, #1
    bls .Lml_refresh_retire
    movs r6, #0
.Lml_refresh_switch:
    ldr r0, =0x28128a74
    ldrb.w r0, [r0, r6, lsl #1]
    cmp r0, #2
    bne .Lml_refresh_next_switch
    ldr r3, =0x28d96085
    blx r3
    mov r1, r6
    add r2, sp, #56
    movs r3, #8
    bl microlooper_native_assignment_ids
    cmp r0, #8
    it hi
    movhi r0, #8                 @ native per-switch fixed slot capacity
    mov r7, r0
    movs r8, #0
.Lml_refresh_id:
    cmp r8, r7
    bhs .Lml_refresh_next_switch
    add r0, sp, #56
    ldr.w r9, [r0, r8, lsl #2]
    movs r0, #0
    str r0, [sp]
    str r0, [sp, #4]
    mov r1, r9
    mov r2, sp
    ldr r3, =0x28e0fe95
    blx r3
    cmp r0, #0
    blt .Lml_refresh_next_id
    ldr r0, [sp, #1]
    movw r1, #ML_MODEL
    cmp r0, r1
    bne .Lml_refresh_next_id
    movs r0, #0xff
    strb r0, [sp, #55]
    movs r0, #0
    mov r1, r9
    add r2, sp, #55
    ldr r3, =0x28e04515
    blx r3
    cmp r0, #0
    blt .Lml_refresh_next_id
    ldrb r0, [sp, #55]
    cmp r0, #0
    bne .Lml_refresh_next_id
    mov r0, r9
    bl microlooper_controller_object
    cmp r0, #0
    beq .Lml_refresh_next_id
    mov r10, r0
    adr.w r5, microlooper_controller_routes
    movs r2, #ML_ROUTE_COUNT
    movs r3, #0                  @ first free record
.Lml_refresh_find:
    ldr r0, [r5, #56]
    cbnz r0, .Lml_refresh_find_active
    cmp r3, #0
    it eq
    moveq r3, r5
    b .Lml_refresh_find_next
.Lml_refresh_find_active:
    cmp r0, r10
    bne .Lml_refresh_find_next
    str r9, [r5, #40]            @ retained object can move to another grid ID
    str r9, [r5, #8]
    b .Lml_refresh_found
.Lml_refresh_find_next:
    adds r5, #ML_ROUTE_SIZE
    subs r2, #1
    bne .Lml_refresh_find
    cmp r3, #0
    beq .Lml_refresh_next_id       @ cannot occur for16 valid native grid IDs
    mov r5, r3
    mov r0, r5
    bl microlooper_binding_reset
    movs r0, #0
    str r0, [r5, #32]            @ native tone handle0, as graph mutex/getters
    adr.w r0, microlooper_controller_write
    orr r0, r0, #1
    str r0, [r5, #36]
    str r9, [r5, #40]
    adr.w r1, microlooper_controller_generation
    ldr r0, [r1]
    adds r0, #1
    str r0, [r1]
    str r0, [r5, #44]
    movw r0, #ML_MODEL
    str r0, [r5, #48]
    movs r0, #0
    str r0, [r5, #52]
    str r0, [r5, #60]
    str r10, [r5, #56]
    ldr.w r0, [r10, #0x9f0]
    str r0, [r5, #64]
.Lml_refresh_found:
    movs r0, #1
    lsl.w r0, r0, r6
    ldr r1, [r5, #60]
    orrs r0, r1
    str r0, [r5, #60]
.Lml_refresh_next_id:
    add.w r8, r8, #1
    b .Lml_refresh_id
.Lml_refresh_next_switch:
    adds r6, #1
    cmp r6, #5
    bne .Lml_refresh_switch
.Lml_refresh_retire:
    adr.w r5, microlooper_controller_routes
    movs r6, #ML_ROUTE_COUNT
.Lml_refresh_record:
    ldr r0, [r5, #56]
    cmp r0, #0
    beq .Lml_refresh_record_next
    ldr r7, [r5, #60]
    cbnz r7, .Lml_refresh_keep
    movs r0, #0
    str r0, [sp]
    str r0, [sp, #4]
    ldr r1, [r5, #40]
    mov r2, sp
    ldr r3, =0x28e0fe95
    blx r3
    cmp r0, #0
    blt .Lml_refresh_retired
    ldr r0, [sp, #1]
    movw r1, #ML_MODEL
    cmp r0, r1
    bne .Lml_refresh_retired
    ldr r0, [r5, #56]
    ldr r1, [r0, #0x24]
    tst r1, #1
    beq .Lml_refresh_retired
    ldr.w r0, [r0, #0x9f0]
    ldr r1, [r5, #64]
    cmp r0, r1
    bne .Lml_refresh_retired
    mov r0, r5
    add r1, r5, #32
    bl microlooper_binding_suspend
    ldr r0, [r5, #52]
    and.w r1, r11, r0
    mov r0, r5
    movs r2, #0
    add r3, r5, #32
    bl microlooper_binding_update @ rearm only after physical release, while ineligible
    b .Lml_refresh_record_next
.Lml_refresh_retired:
    mov r0, r5
    bl microlooper_binding_reset
    movs r0, #0
    str r0, [r5, #56]
    str r0, [r5, #52]
    b .Lml_refresh_record_next
.Lml_refresh_keep:
    ldr r0, [r5, #52]
    cmp r0, r7
    beq .Lml_refresh_init
    cbz r0, .Lml_refresh_adopt
    mov r0, r5
    add r1, r5, #32
    bl microlooper_binding_suspend
.Lml_refresh_adopt:
    str r7, [r5, #52]
.Lml_refresh_init:
    ldr r0, [r5, #28]
    cbz r0, .Lml_refresh_init_run
    ldr r0, [r5]
    tst r0, #4
    beq .Lml_refresh_record_next
.Lml_refresh_init_run:
    ldr r3, =0x28da6459
    blx r3
    mov r2, r0
    and.w r1, r11, r7
    mov r0, r5
    add r3, r5, #32
    bl microlooper_binding_update
.Lml_refresh_record_next:
    adds r5, #ML_ROUTE_SIZE
    subs r6, #1
    bne .Lml_refresh_record
    add sp, #100
    pop {r4-r11, pc}
    .ltorg

@ (stomp_obj, pressed_mask)->mask of switches with eligible Micro bindings.
.thumb_func
microlooper_controller_drive:
    push {r4-r8, lr}
    mov r7, r1
    movs r8, #0
    ldr r3, =0x28da6459
    blx r3
    mov r6, r0
    adr.w r4, microlooper_controller_routes
    movs r5, #ML_ROUTE_COUNT
.Lml_drive_next:
    ldr r0, [r4, #56]
    cbz r0, .Lml_drive_skip
    ldr r0, [r4, #60]
    cbz r0, .Lml_drive_skip
    ldr r0, [r4, #52]
    orr.w r8, r8, r0
    and.w r1, r7, r0
    mov r0, r4
    mov r2, r6
    add r3, r4, #32
    bl microlooper_binding_update
.Lml_drive_skip:
    adds r4, #ML_ROUTE_SIZE
    subs r5, #1
    bne .Lml_drive_next
    mov r0, r8
    pop {r4-r8, pc}
    .ltorg

@ Shared owner veneer supplies (event,obj,original_handler,lp_event_or0).
.thumb_func
microlooper_controller_key:
    push {r4-r10, lr}
    mov r4, r0
    mov r5, r1
    mov r6, r2
    mov r7, r3
    ldrb r0, [r4]
    cmp r0, #1
    bne .Lml_key_pass
    ldrb r8, [r4, #1]
    sub.w r8, r8, #12
    cmp r8, #5
    bhs .Lml_key_pass
    mov r0, r5
    bl microlooper_controller_input_lock
    mov r0, r5
    bl microlooper_controller_refresh
    mov r0, r5
    bl microlooper_controller_pressed
    movs r1, #1
    lsl.w r9, r1, r8
    ldr r10, [r4, #4]
    cmp r10, #1
    it eq
    orreq r0, r0, r9
    cmp r10, #2
    it eq
    biceq r0, r0, r9
    mov r1, r0
    mov r0, r5
    bl microlooper_controller_drive
    and.w r8, r0, r9
    mov r0, r5
    bl microlooper_controller_input_unlock
    cmp r8, #0
    beq .Lml_key_pass
    cmp r10, #5
    beq .Lml_key_out
    mov r0, r4
    mov r1, r5
    blx r6                      @ ordinary assigned blocks still receive event
    b .Lml_key_out
.Lml_key_pass:
    mov r0, r4
    mov r1, r5
    mov r2, r6
    cmp r7, #0
    beq .Lml_key_stock
    blx r7
    b .Lml_key_out
.Lml_key_stock:
    blx r6
.Lml_key_out:
    pop {r4-r10, pc}

.thumb_func
microlooper_controller_tick:
    push {r4, lr}
    mov r4, r1
    mov r0, r4
    bl microlooper_controller_input_lock
    mov r0, r4
    bl microlooper_controller_refresh
    mov r0, r4
    bl microlooper_controller_pressed
    mov r1, r0
    mov r0, r4
    bl microlooper_controller_drive
    mov r0, r4
    bl microlooper_controller_input_unlock
    pop {r4, pc}

@ Primitive hooks enter with native(manager,blockobject,...). Keep the graph
@ mutex around original call and its own nested native transactions. Before
@ object initialization/destruction, stop old overdub and retire exact ownership.
.thumb_func
microlooper_controller_object_before:
    push {r4-r6, lr}
    mov r6, r1
    bl microlooper_controller_lock
    adr.w r4, microlooper_controller_routes
    movs r5, #ML_ROUTE_COUNT
.Lml_object_retire:
    ldr r0, [r4, #56]
    cmp r0, r6
    bne .Lml_object_retire_next
    mov r0, r4
    add r1, r4, #32
    bl microlooper_binding_suspend
.Lml_object_retire_next:
    adds r4, #ML_ROUTE_SIZE
    subs r5, #1
    bne .Lml_object_retire
    pop {r4-r6, pc}
    .ltorg

@ Structural grid operations can retain DSP allocations while changing IDs.
@ Quiesce affected inclusive ID range before native mutation, with the graph
@ mutex held until the chain's after handler releases it.
.thumb_func
microlooper_controller_model_before:
    mov r2, r1
    b microlooper_controller_range_before
.thumb_func
microlooper_controller_up_before:
    adds r2, r1, #1
    b microlooper_controller_range_before
.thumb_func
microlooper_controller_down_before:
    subs r2, r1, #1
.thumb_func
microlooper_controller_range_before:
    push {r4-r8, lr}
    mov r6, r1
    mov r7, r2
    cmp r6, r7
    bls .Lml_range_ordered
    mov r0, r6
    mov r6, r7
    mov r7, r0
.Lml_range_ordered:
    bl microlooper_controller_lock
    adr.w r4, microlooper_controller_routes
    movs r5, #ML_ROUTE_COUNT
.Lml_range_next:
    ldr r0, [r4, #56]
    cbz r0, .Lml_range_skip
    ldr r0, [r4, #40]
    cmp r0, r6
    blo .Lml_range_skip
    cmp r0, r7
    bhi .Lml_range_skip
    mov r0, r4
    add r1, r4, #32
    bl microlooper_binding_suspend
.Lml_range_skip:
    adds r4, #ML_ROUTE_SIZE
    subs r5, #1
    bne .Lml_range_next
    pop {r4-r8, pc}
    .ltorg

@ Native bypass writes retain their ordinary UI/snapshot meaning. Only an
@ actual bypass-state transition cancels that block's gesture. Recalling an
@ unchanged snapshot bypass must not stop a playing loop.
.thumb_func
microlooper_controller_lower_bypass_before:
    ldrb r3, [r1]
    cmp r3, #6                   @ ordinary effect grid address
    bne microlooper_controller_lock
    ldr r3, [r1, #4]
    cmp r3, #15
    bhi microlooper_controller_lock
    cmp r3, #8
    it hs
    addhs r3, #2
    adds r1, r3, #1
    movs r0, #0
    b microlooper_controller_bypass_before
.thumb_func
microlooper_controller_bypass_before:
    push {r4-r6, lr}
    sub sp, #8
    mov r4, r1
    mov r5, r2
    bl microlooper_controller_lock
    movs r0, #0xff
    strb r0, [sp]
    movs r0, #0
    mov r1, r4
    mov r2, sp
    ldr r3, =0x28e04515
    blx r3
    cmp r0, #0
    blt .Lml_bypass_before_out
    ldrb r0, [sp]
    cmp r0, r5
    beq .Lml_bypass_before_out
    movs r0, #0
    mov r1, r4
    mov r2, r4
    bl microlooper_controller_range_before
    bl microlooper_controller_unlock @ range helper took its own recursive lock
.Lml_bypass_before_out:
    add sp, #8
    pop {r4-r6, pc}
    .ltorg

@ Explicit lifecycle veneer supplies real native(status,original_blockobj,kind).
@ kind1 initializer: success establishes a new allocation even at reused address.
@ kind2 destructor: native in-use/link fields establish loss even on partial error.
@ kind0 retained-ID mutations: preserve live ownership and retarget grid IDs.
.thumb_func
microlooper_controller_after:
    push {r4-r8, lr}
    mov r6, r0
    mov r7, r1
    mov r8, r2
    adr.w r4, microlooper_controller_routes
    movs r5, #ML_ROUTE_COUNT
.Lml_after_record:
    ldr r0, [r4, #56]
    cbz r0, .Lml_after_next
    cmp r8, #1
    bne .Lml_after_reindex
    cmp r6, #0
    blt .Lml_after_reindex
    cmp r0, r7
    beq .Lml_after_lost
    ldr.w r0, [r7, #0x9f0]
    ldr r1, [r4, #64]
    cmp r0, r1
    beq .Lml_after_lost
.Lml_after_reindex:
    movs r2, #1
.Lml_after_find_id:
    mov r0, r2
    push {r2, r3}
    bl microlooper_controller_object
    pop {r2, r3}
    cbz r0, .Lml_after_find_next
    ldr.w r1, [r0, #0x9f0]
    ldr r3, [r4, #64]
    cmp r1, r3
    beq .Lml_after_found_id
.Lml_after_find_next:
    adds r2, #1
    cmp r2, #9
    it eq
    moveq r2, #11
    cmp r2, #19
    bne .Lml_after_find_id
.Lml_after_lost:
    mov r0, r4
    bl microlooper_binding_reset
    movs r0, #0
    str r0, [r4, #56]
    str r0, [r4, #52]
    str r0, [r4, #60]
    b .Lml_after_next
.Lml_after_found_id:
    str r0, [r4, #56]
    str r2, [r4, #40]
    str r2, [r4, #8]
.Lml_after_next:
    adds r4, #ML_ROUTE_SIZE
    subs r5, #1
    bne .Lml_after_record
    bl microlooper_controller_unlock
    pop {r4-r8, pc}
    .ltorg

@ Every installed transport write verifies the current primary identity, even
@ for our whitelisted LR. A retained native link never authorizes slot writes
@ into another model. The standalone raw ABI helper remains independently usable.
.thumb_func
microlooper_controller_write:
    push {r0-r7, lr}
    sub sp, #60
    movs r2, #0
    str r2, [sp]
    str r2, [sp, #4]
    mov r2, sp
    ldr r3, =0x28e0fe95
    blx r3
    cmp r0, #0
    blt .Lml_controller_write_refuse
    ldr r0, [sp, #1]
    movw r1, #ML_MODEL
    cmp r0, r1
    bne .Lml_controller_write_wrong
    add sp, #60
    pop {r0-r7, lr}
    b microlooper_native_write
.Lml_controller_write_wrong:
    mvn r0, #2
.Lml_controller_write_refuse:
    mov r12, r0
    add sp, #60
    pop {r0-r7, lr}
    mov r0, r12
    bx lr
    .ltorg

.balign 4
microlooper_controller_generation:
    .word 0
microlooper_controller_routes:
    .space ML_ROUTE_COUNT * ML_ROUTE_SIZE

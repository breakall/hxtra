// SPDX-License-Identifier: GPL-3.0-or-later
// Native C callbacks, not process CALL/RTS entries.
// Init: R4 points at the allocator's instance descriptor; DM0 is private DM.
// Control: R4=PID, R8=value-word pointer, R12=the same instance descriptor.
// The native scalar C environment supplies M7=-1,M14=1, L7=0 and the frame at I6.
// Only C-volatile R0/R1/I4/I12 and arithmetic flags are used. I6/I7 restored.
// Private DM is199 words; no private PM, shared storage or SDRAM clear.
// Clearing marker20 causes the audio core's bounded fresh-instance reset.
// Transport10/11 start low; normal parameters5..9 arrive through model controls.
// Before first processing (marker20=0), discard transport control delivery.
// Native construction delivers its saved controls synchronously before return;
// the new instance must not be published to audio midway through construction.
// First processing therefore observes low transport and arms the first gesture.
.section pm MICROLOOPER_INIT_PM_BASE
MICROLOOPER_INIT:
    I4 = R4;
    R0 = DM(0,I4);
    I4 = R0;
    R0 = 0;
    DM(10,I4) = R0;
    DM(11,I4) = R0;
    DM(20,I4) = R0;
microlooper_c_return:
    R0 = 0;
    I12 = DM(M7,I6);
    JUMP (M14,I12) (DB);
    RFRAME;
    NOP;

MICROLOOPER_CONTROL:
    R0 = 5;
    COMPU(R4,R0);
    IF LT JUMP microlooper_c_return;
    R0 = 11;
    COMPU(R4,R0);
    IF GT JUMP microlooper_c_return;
    I4 = R12;
    R1 = DM(0,I4);
    R0 = 10;
    COMPU(R4,R0);
    IF LT JUMP microlooper_control_write;
    I4 = R1;
    R0 = DM(20,I4);
    R0 = PASS R0;
    IF EQ JUMP microlooper_c_return;
microlooper_control_write:
    R1 = R1 + R4;
    I4 = R8;
    R0 = DM(0,I4);
    I4 = R1;
    DM(0,I4) = R0;
    JUMP microlooper_c_return;

// SPDX-License-Identifier: GPL-3.0-or-later
// Native scalar C callbacks: init(R4=descriptor); control(R4=PID,R8=value*,R12=descriptor).
// The caller supplies M7=-1,M14=1,L7=0 and its frame in I6. Only C-volatile
// R0/R1,I4/I12 and arithmetic flags are changed. Runtime initialization belongs
// to first audio processing; framework words0..3 and runtime state stay untouched.
.section pm GLASSHOUSE_INIT_PM_BASE
GLASSHOUSE_INIT:
    R1 = 2;
    JUMP glasshouse_init_channels;
GLASSHOUSE_INIT_MONO:
    R1 = 1;
glasshouse_init_channels:
    I4 = R4;
    R0 = DM(0,I4);
    I4 = R0;
    DM(5,I4) = R1;
    R0 = 0;
    DM(4,I4) = R0;
    DM(6,I4) = R0;
    DM(7,I4) = R0;
GLASSHOUSE_DEFAULTS

glasshouse_c_return:
    R0 = 0;
    I12 = DM(M7,I6);
    JUMP (M14,I12) (DB);
    RFRAME;
    NOP;

GLASSHOUSE_CONTROL:
    R0 = 16;
    COMPU(R4,R0);
    IF LT JUMP glasshouse_c_return;
    R0 = 54;
    COMPU(R4,R0);
    IF GT JUMP glasshouse_c_return;
    R0 = 33;
    COMPU(R4,R0);
    IF EQ JUMP glasshouse_c_return;
    I4 = R8;
    R0 = DM(0,I4);
    R1 = 40;
    COMPU(R4,R1);
    IF GE JUMP glasshouse_control_integer;
    R1 = 30;
    COMPU(R4,R1);
    IF LT JUMP glasshouse_control_float;
    R1 = 32;
    COMPU(R4,R1);
    IF GT JUMP glasshouse_control_float;
    // Native bool options become source-style floating point0/1.
    R1 = 1;
    COMPU(R0,R1);
    IF GT JUMP glasshouse_c_return;
    F0 = FLOAT R0;
    JUMP glasshouse_control_write;
glasshouse_control_float:
    // Nonnegative finite IEEE values0..1 sort as unsigned words. Rejecting
    // larger patterns also rejects NaN,infinity and all negative values.
    R1 = 0x80000000;
    COMPU(R0,R1);
    IF EQ JUMP glasshouse_control_write; // IEEE negative zero is also in0..1.
    R1 = 0x3f800000;
    COMPU(R0,R1);
    IF GT JUMP glasshouse_c_return;
    JUMP glasshouse_control_write;
glasshouse_control_integer:
    R1 = 52;
    COMPU(R4,R1);
    IF GE JUMP glasshouse_control_bool;
    R1 = 2;
    JUMP glasshouse_control_limit;
glasshouse_control_bool:
    R1 = 1;
glasshouse_control_limit:
    COMPU(R0,R1);
    IF GT JUMP glasshouse_c_return;
glasshouse_control_write:
    I4 = R12;
    R1 = DM(0,I4);
    I12 = R1;
    R1 = R1 + R4;
    I4 = R1;
    // Source SetAux and SetBypass observe edges when delivered, even when
    // both levels arrive before the next audio block. Pending edges belong
    // to this live instance; construction/restored highs cannot latch them.
    R1 = 1;
    COMPU(R0,R1);
    IF NE JUMP glasshouse_control_store;
    R1 = 52;
    COMPU(R4,R1);
    IF EQ JUMP glasshouse_control_aux_edge;
    R1 = 54;
    COMPU(R4,R1);
    IF NE JUMP glasshouse_control_store;
    R1 = DM(0,I4);
    R1 = PASS R1;
    IF NE JUMP glasshouse_control_store;
    I4 = I12;
    R1 = DM(4,I4);
    R1 = PASS R1;
    IF EQ JUMP glasshouse_control_store;
    DM(7,I4) = R0;
    JUMP glasshouse_control_store;
glasshouse_control_aux_edge:
    R1 = DM(0,I4);
    R1 = PASS R1;
    IF NE JUMP glasshouse_control_store;
    I4 = I12;
    R1 = DM(4,I4);
    R1 = PASS R1;
    IF EQ JUMP glasshouse_control_store;
    R1 = DM(47,I4);
    R1 = R1 - 1;
    IF NE JUMP glasshouse_control_store;
    DM(6,I4) = R0;
glasshouse_control_store:
    R1 = I12;
    R1 = R1 + R4;
    I4 = R1;
    DM(0,I4) = R0;
    JUMP glasshouse_c_return;

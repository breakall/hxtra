// Development diagnostic only: NOT a production micro-looper or verified stereo
// firmware adapter. The caller supplies I0 (49-word private state), I1/I2
// (32-word interleaved L/R input/output for 16 frames). Input/output may be the
// same buffer; they must not overlap state or ring. The actual stereo FX host
// channel pointers/instance descriptor still require an on-device probe.
//
// State normal-word offsets: 0 ring begin, 1 ring end (exclusive), 2 write word
// offset, 3 valid frames, 4 calls, 5 invalid configurations, 6/7 input L/R XOR,
// 8 listen (nonzero records); 32..48 save area. Caller zeroes counters, cursor
// and valid count on new instance, without clearing the large ring.
// Ring must be an even number of words >=2 in caller-owned external RAM;
// configuration failure passes dry audio and increments errors, never writes
// the ring. The extent is a caller contract, NOT an allocation inferred here.
// MODE1 and all modified data/index/length registers are restored.
.equ PROBE_SAVE, 32
.equ PEYEN, 0x200000
.equ BDCST9, 0x400000
.section pm KIT_PM_BASE
MICROLOOPER_PROBE_ENTRY:
    DM(PROBE_SAVE, I0) = MODE1;
    BIT CLR MODE1 PEYEN | BDCST9;
    DM(PROBE_SAVE + 1, I0) = R0;
    DM(PROBE_SAVE + 2, I0) = R1;
    DM(PROBE_SAVE + 3, I0) = R2;
    DM(PROBE_SAVE + 4, I0) = R3;
    DM(PROBE_SAVE + 5, I0) = R4;
    DM(PROBE_SAVE + 6, I0) = R5;
    DM(PROBE_SAVE + 7, I0) = R6;
    DM(PROBE_SAVE + 8, I0) = R7;
    DM(PROBE_SAVE + 9, I0) = R8;
    DM(PROBE_SAVE + 10, I0) = R9;
    R0 = I4;
    DM(PROBE_SAVE + 11, I0) = R0;
    R0 = L4;
    DM(PROBE_SAVE + 12, I0) = R0;
    R0 = I5;
    DM(PROBE_SAVE + 13, I0) = R0;
    R0 = L5;
    DM(PROBE_SAVE + 14, I0) = R0;
    R0 = I6;
    DM(PROBE_SAVE + 15, I0) = R0;
    R0 = L6;
    DM(PROBE_SAVE + 16, I0) = R0;
    L4 = 0;
    L5 = 0;
    L6 = 0;
    I4 = I1;
    I5 = I2;
    R0 = DM(4, I0);
    R0 = R0 + 1;
    DM(4, I0) = R0;
    R4 = DM(6, I0);
    R5 = DM(7, I0);
    R6 = DM(8, I0);
    R9 = DM(0, I0);
    R8 = DM(1, I0);
    R2 = 0x200000;
    COMPU(R9, R2);
    IF LT JUMP probe_bad;
    R2 = 0x4000000;
    COMPU(R8, R2);
    IF GT JUMP probe_bad;
    COMPU(R8, R9);
    IF LE JUMP probe_bad;
    R3 = R8 - R9;
    R7 = 1;
    R7 = R3 AND R7;
    R7 = PASS R7;
    IF NE JUMP probe_bad;
    R2 = DM(2, I0);
    COMPU(R2, R3);
    IF GE JUMP probe_bad;
    R7 = 1;
    R7 = R2 AND R7;
    R7 = PASS R7;
    IF NE JUMP probe_bad;
    R2 = R9 + R2;
    I6 = R2;
    JUMP probe_audio;
probe_bad:
    R0 = DM(5, I0);
    R0 = R0 + 1;
    DM(5, I0) = R0;
    R6 = 0;
probe_audio:
    LCNTR = 16, DO probe_last UNTIL LCE;
      R0 = DM(I4, 1);
      R1 = DM(I4, 1);
      R4 = R4 XOR R0;
      R5 = R5 XOR R1;
      R6 = PASS R6;
      IF EQ JUMP probe_thru;
      DM(I6, 1) = R0;
      DM(I6, 1) = R1;
      R2 = I6;
      COMP(R2, R8);
      IF EQ I6 = R9;
probe_thru:
      DM(I5, 1) = R0;
probe_last: DM(I5, 1) = R1;
    DM(6, I0) = R4;
    DM(7, I0) = R5;
    R6 = PASS R6;
    IF EQ JUMP probe_return;
    R2 = I6;
    R2 = R2 - R9;
    DM(2, I0) = R2;
    R3 = LSHIFT R3 BY -1;
    R2 = DM(3, I0);
    R7 = 16;
    R2 = R2 + R7;
    R2 = MIN(R2, R3);
    DM(3, I0) = R2;
probe_return:
    R0 = DM(PROBE_SAVE + 11, I0);
    I4 = R0;
    R0 = DM(PROBE_SAVE + 12, I0);
    L4 = R0;
    R0 = DM(PROBE_SAVE + 13, I0);
    I5 = R0;
    R0 = DM(PROBE_SAVE + 14, I0);
    L5 = R0;
    R0 = DM(PROBE_SAVE + 15, I0);
    I6 = R0;
    R0 = DM(PROBE_SAVE + 16, I0);
    L6 = R0;
    R0 = DM(PROBE_SAVE + 1, I0);
    R1 = DM(PROBE_SAVE + 2, I0);
    R2 = DM(PROBE_SAVE + 3, I0);
    R3 = DM(PROBE_SAVE + 4, I0);
    R4 = DM(PROBE_SAVE + 5, I0);
    R5 = DM(PROBE_SAVE + 6, I0);
    R6 = DM(PROBE_SAVE + 7, I0);
    R7 = DM(PROBE_SAVE + 8, I0);
    R8 = DM(PROBE_SAVE + 9, I0);
    R9 = DM(PROBE_SAVE + 10, I0);
    MODE1 = DM(PROBE_SAVE, I0);
    NOP;
    RTS (LR);

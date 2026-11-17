// Native-context diagnostic, NOT a verified stereo audio adapter.
// Caller contract: I0 points to at least200 DM words; words0..159 are untouched.
// No audio pointer is
// dereferenced; this routine does not pass audio through and must not replace
// a stock processing primitive in a user-facing image.
//
// Snapshot160..175: magic, calls, I0,I1,I2,I3,I8,B1,L1,B2,L2,MODE1,
// instance candidate, SDRAM begin,end, plausible extent. "Plausible" is a
// range check only; it does not establish allocator ownership or stereo ABI.
// Offsets176..179 save ASTAT/STKY;180 publishes odd/even snapshot sequence;
// 181..189 are reserved for the diagnostic frame publisher;192..199 save registers (including SIMD padding).
// No shared/global storage. The wrapper below is AcousticSim3.80 diagnostic only.
.equ SNAPSHOT, 160
.equ SAVE, 192
.equ SOURCE_SEQUENCE, 180
.equ PEYEN, 0x200000
.equ BDCST9, 0x400000
.section pm KIT_PM_BASE
MICROLOOPER_ADAPTER_CONTEXT:
    DM(SAVE + 6, I0) = MODE1;
    BIT CLR MODE1 PEYEN | BDCST9;
    NOP;
    DM(176, I0) = ASTATX;
    DM(177, I0) = ASTATY;
    DM(178, I0) = STKYX;
    DM(179, I0) = STKYY;
    DM(SAVE + 0, I0) = R0;
    DM(SAVE + 1, I0) = R1;
    DM(SAVE + 2, I0) = R2;
    DM(SAVE + 3, I0) = R3;
    R0 = I4;
    DM(SAVE + 4, I0) = R0;
    R0 = L4;
    DM(SAVE + 5, I0) = R0;
    L4 = 0;
    // Invalidate before any snapshot store. Readers never spin on the audio thread.
    R0 = DM(SOURCE_SEQUENCE, I0);
    R1 = 1;
    R0 = R0 OR R1;
    DM(SOURCE_SEQUENCE, I0) = R0;
    R0 = 0x6d6c6131;
    DM(SNAPSHOT + 0, I0) = R0;
    R0 = DM(SNAPSHOT + 1, I0);
    R0 = R0 + 1;
    DM(SNAPSHOT + 1, I0) = R0;
    R0 = I0;
    DM(SNAPSHOT + 2, I0) = R0;
    R0 = I1;
    DM(SNAPSHOT + 3, I0) = R0;
    R0 = I2;
    DM(SNAPSHOT + 4, I0) = R0;
    R0 = I3;
    DM(SNAPSHOT + 5, I0) = R0;
    R0 = I8;
    DM(SNAPSHOT + 6, I0) = R0;
    R0 = B1;
    DM(SNAPSHOT + 7, I0) = R0;
    R0 = L1;
    DM(SNAPSHOT + 8, I0) = R0;
    R0 = B2;
    DM(SNAPSHOT + 9, I0) = R0;
    R0 = L2;
    DM(SNAPSHOT + 10, I0) = R0;
    R0 = DM(SAVE + 6, I0);
    DM(SNAPSHOT + 11, I0) = R0;
    R0 = 0;
    DM(SNAPSHOT + 12, I0) = R0;
    DM(SNAPSHOT + 13, I0) = R0;
    DM(SNAPSHOT + 14, I0) = R0;
    DM(SNAPSHOT + 15, I0) = R0;
    // Require the complete3-word call record /8-word descriptor in SRAM.
    // Clearing bit17 folds block1 onto0 and block3 onto2 without admitting
    // ROM/reserved holes. Original pointers remain untouched for dereference.
    R0 = I3;
    R1 = 0xfffdffff;
    R0 = R0 AND R1;
    R1 = 0x92000;
    COMPU(R0, R1);
    IF LT JUMP adapter_done;
    R1 = 0x9dffd;
    COMPU(R0, R1);
    IF LE JUMP adapter_call_valid;
    R1 = 0xc0000;
    COMPU(R0, R1);
    IF LT JUMP adapter_done;
    R1 = 0xc7ffd;
    COMPU(R0, R1);
    IF GT JUMP adapter_done;
adapter_call_valid:
    R0 = DM(2, I3);
    DM(SNAPSHOT + 12, I0) = R0;
    R2 = R0;
    R1 = 0xfffdffff;
    R0 = R0 AND R1;
    R1 = 0x92000;
    COMPU(R0, R1);
    IF LT JUMP adapter_done;
    R1 = 0x9dff8;
    COMPU(R0, R1);
    IF LE JUMP adapter_descriptor_valid;
    R1 = 0xc0000;
    COMPU(R0, R1);
    IF LT JUMP adapter_done;
    R1 = 0xc7ff8;
    COMPU(R0, R1);
    IF GT JUMP adapter_done;
adapter_descriptor_valid:
    I4 = R2;
    R0 = DM(6, I4);
    R1 = DM(7, I4);
    DM(SNAPSHOT + 13, I0) = R0;
    DM(SNAPSHOT + 14, I0) = R1;
    R2 = 0x200000;
    COMPU(R0, R2);
    IF LT JUMP adapter_done;
    R2 = 0x4000000;
    COMPU(R1, R2);
    IF GT JUMP adapter_done;
    COMPU(R1, R0);
    IF LE JUMP adapter_done;
    R2 = R1 - R0;
    R3 = 48000;
    COMPU(R2, R3);
    IF LT JUMP adapter_done;
    R0 = 1;
    DM(SNAPSHOT + 15, I0) = R0;
adapter_done:
    R0 = DM(SOURCE_SEQUENCE, I0);
    R0 = R0 + 1;
    DM(SOURCE_SEQUENCE, I0) = R0;
    R0 = DM(SAVE + 4, I0);
    I4 = R0;
    R0 = DM(SAVE + 5, I0);
    L4 = R0;
    R0 = DM(SAVE + 0, I0);
    R1 = DM(SAVE + 1, I0);
    R2 = DM(SAVE + 2, I0);
    R3 = DM(SAVE + 3, I0);
    STKYX = DM(178, I0);
    STKYY = DM(179, I0);
    ASTATX = DM(176, I0);
    ASTATY = DM(177, I0);
    MODE1 = DM(SAVE + 6, I0);
    NOP;
    RTS (LR);

// Requires actual graph/private DM allocation >=200, original init/control,
// original AcousticSim parameters and SDRAM metadata. Builder must prove those
// conditions before using this entry. No hardware/audio safety claim is made.
MICROLOOPER_ADAPTER_ACOUSTIC_DIAGNOSTIC:
    CALL MICROLOOPER_ADAPTER_CONTEXT;
    JUMP 0x8e9e3;

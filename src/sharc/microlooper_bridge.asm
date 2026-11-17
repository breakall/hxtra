// SPDX-License-Identifier: GPL-3.0-or-later
// Native descriptor residency and mono Tape capture observed on an HX Stomp.
// Stereo separation, all modes and real-time timing remain qualification gates.
// Contract: caller initializes private I0 allocation (199 normal words),
// resets core marker DM20 on every new graph, and supplies I1 input/I2 output
// as contiguous planar L[16],R[16] float32 words. I3 is a call record whose
// word2 points to an instance record, with SDRAM begin/end at words6/7.
// Header/tag interpretation, native dispatch and float layout remain hardware
// gates. The separate native init/lifecycle adapters establish reset/ownership.
//
// DM153..184: private interleaved stereo buffer, used in place by audio core.
// DM185..194: MODE1,R0,R1,R2,I1,I2,I4,L4,I5,L5 spills;195..198 ASTATX/Y,STKYX/Y.
// No global storage, instance count policy, DMA or large initialization clear.
// Bad call/instance pointer produces zero ring extent; the existing core
// allocation guard supplies dry passthrough without dereferencing that ring.
// Native I0/input/output extents remain caller contracts, not guessed here.
.equ PEYEN, 0x200000
.equ BDCST9, 0x400000
.section pm BRIDGE_PM_BASE
MICROLOOPER_BRIDGE_ENTRY:
    DM(185, I0) = MODE1;
    BIT CLR MODE1 PEYEN | BDCST9;
    NOP;
    DM(186, I0) = R0;
    DM(187, I0) = R1;
    DM(188, I0) = R2;
    DM(195, I0) = ASTATX;
    DM(196, I0) = ASTATY;
    DM(197, I0) = STKYX;
    DM(198, I0) = STKYY;
    R0 = I1;
    DM(189, I0) = R0;
    R0 = I2;
    DM(190, I0) = R0;
    R0 = I4;
    DM(191, I0) = R0;
    R0 = L4;
    DM(192, I0) = R0;
    L4 = 0;
    R0 = I5;
    DM(193, I0) = R0;
    R0 = L5;
    DM(194, I0) = R0;
    L5 = 0;

    // Check the call record before reading its instance pointer.
    R0 = I3;
    R2 = 3;
    CALL ml_bridge_internal_extent;
    IF GT JUMP ml_bridge_bad_descriptor;
    R0 = DM(2, I3);
    // Native instances can live in Heap6 DDR2, not just internal RAM. The
    // linker pins this heap's setup; require all eight descriptor words to fit.
    I4 = R0;
    R1 = MICROLOOPER_DESCRIPTOR_HEAP_BEGIN;
    R1 = R0 - R1;
    R2 = MICROLOOPER_DESCRIPTOR_HEAP_LAST;
    COMPU(R1, R2);
    IF LE JUMP ml_bridge_descriptor_valid;
    R2 = 8;
    CALL ml_bridge_internal_extent;
    IF GT JUMP ml_bridge_bad_descriptor;
ml_bridge_descriptor_valid:
    R0 = DM(6, I4);
    R1 = DM(7, I4);
    DM(12, I0) = R0;
    DM(13, I0) = R1;
    JUMP ml_bridge_input;
ml_bridge_bad_descriptor:
    R0 = 0;
    DM(12, I0) = R0;
    DM(13, I0) = R0;

ml_bridge_input:
    I4 = I1;
    I5 = I0;
    MODIFY(I5, 153);
    R2 = 16;
ml_bridge_interleave:
    R1 = DM(16, I4);
    R0 = DM(I4, 1);
    DM(I5, 1) = R0;
    DM(I5, 1) = R1;
    R2 = R2 - 1;
    IF NE JUMP ml_bridge_interleave;

    // The audio core accepts the same private buffer for input and output.
    MODIFY(I5, -32);
    I1 = I5;
    I2 = I5;
    CALL MICROLOOPER_CORE_ENTRY;

    I4 = I1;
    R0 = DM(190, I0);
    I5 = R0;
    R2 = 16;
ml_bridge_planar:
    R0 = DM(I4, 1);
    R1 = DM(I4, 1);
    DM(16, I5) = R1;
    DM(I5, 1) = R0;
    R2 = R2 - 1;
    IF NE JUMP ml_bridge_planar;

    R0 = DM(189, I0);
    I1 = R0;
    R0 = DM(190, I0);
    I2 = R0;
    R0 = DM(191, I0);
    I4 = R0;
    R0 = DM(192, I0);
    L4 = R0;
    R0 = DM(193, I0);
    I5 = R0;
    R0 = DM(194, I0);
    L5 = R0;
    R0 = DM(186, I0);
    R1 = DM(187, I0);
    R2 = DM(188, I0);
    STKYX = DM(197, I0);
    STKYY = DM(198, I0);
    ASTATX = DM(195, I0);
    ASTATY = DM(196, I0);
    MODE1 = DM(185, I0);
    NOP;
    RTS (LR);

// R0 candidate, R2 complete extent in words. Return unsigned LE when valid.
// Clearing bit17 folds SRAM pairs into [92000,9e000) and [c0000,c8000).
// Unsigned subtraction rejects addresses below a window, including ROM/gaps.
// The original pointer is retained in I3 or I4; this routine never dereferences.
ml_bridge_internal_extent:
    R1 = 0xfffdffff;
    R0 = R0 AND R1;
    R1 = 0x92000;
    R0 = R0 - R1;
    R1 = 0xc000;
    R1 = R1 - R2;
    COMPU(R0, R1);
    IF LE RTS (LR);
    R1 = 0x2e000;
    R0 = R0 - R1;
    R1 = 0x8000;
    R1 = R1 - R2;
    COMPU(R0, R1);
    RTS (LR);

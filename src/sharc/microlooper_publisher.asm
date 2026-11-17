// Diagnostic frame publisher only. No native audio pointers are dereferenced.
// Caller I4 points to a verified256-word SPI frame. Source sidecar is an
// explicitly reserved200-word diagnostic allocation; snapshot160..175,
// sequence180, publisher saves181..189. All data/index/MODE1/ASTAT/STKY
// registers are preserved; no hardware loop or retry is used.
// Frame219=tag/version,220=begin,221=16,222..237=payload,238=end.
// Only219..238 are touched; native/GR fields and239..249 remain unchanged.
// A source update during copy leaves destination guards odd. A reader must
// check equal even guards before AND after copying. DMA visibility requires
// hardware qualification; tests establish the encoded store ordering only.
.equ SIDECAR, MICROLOOPER_SIDECAR
.equ PUBLISH_SAVE, SIDECAR + 181
.equ PEYEN, 0x200000
.equ BDCST9, 0x400000
.section pm KIT_PM_BASE
MICROLOOPER_PUBLISH_CONTEXT:
    DM(PUBLISH_SAVE + 0) = MODE1;
    BIT CLR MODE1 PEYEN | BDCST9;
    NOP;
    DM(PUBLISH_SAVE + 1) = ASTATX;
    DM(PUBLISH_SAVE + 2) = ASTATY;
    DM(PUBLISH_SAVE + 3) = STKYX;
    DM(PUBLISH_SAVE + 4) = STKYY;
    DM(PUBLISH_SAVE + 5) = R0;
    DM(PUBLISH_SAVE + 6) = R1;
    DM(PUBLISH_SAVE + 7) = R2;
    DM(PUBLISH_SAVE + 8) = R3;
    R0 = DM(SIDECAR + 180);
    R1 = 1;
    R2 = R0 OR R1;
    // Both guards are invalid before the first payload/tag/count store.
    DM(220, I4) = R2;
    DM(238, I4) = R2;
    R1 = R0 AND R1;
    R1 = PASS R1;
    IF NE JUMP publish_done;
    R1 = DM(SIDECAR + 160);
    R2 = 0x6d6c6131;
    COMP(R1, R2);
    IF NE JUMP publish_done;
    R2 = 0x4d4c0001;
    DM(219, I4) = R2;
    R2 = 16;
    DM(221, I4) = R2;
    R2 = DM(SIDECAR + 160);
    DM(222, I4) = R2;
    R2 = DM(SIDECAR + 161);
    DM(223, I4) = R2;
    R2 = DM(SIDECAR + 162);
    DM(224, I4) = R2;
    R2 = DM(SIDECAR + 163);
    DM(225, I4) = R2;
    R2 = DM(SIDECAR + 164);
    DM(226, I4) = R2;
    R2 = DM(SIDECAR + 165);
    DM(227, I4) = R2;
    R2 = DM(SIDECAR + 166);
    DM(228, I4) = R2;
    R2 = DM(SIDECAR + 167);
    DM(229, I4) = R2;
    R2 = DM(SIDECAR + 168);
    DM(230, I4) = R2;
    R2 = DM(SIDECAR + 169);
    DM(231, I4) = R2;
    R2 = DM(SIDECAR + 170);
    DM(232, I4) = R2;
    R2 = DM(SIDECAR + 171);
    DM(233, I4) = R2;
    R2 = DM(SIDECAR + 172);
    DM(234, I4) = R2;
    R2 = DM(SIDECAR + 173);
    DM(235, I4) = R2;
    R2 = DM(SIDECAR + 174);
    DM(236, I4) = R2;
    R2 = DM(SIDECAR + 175);
    DM(237, I4) = R2;
    R1 = DM(SIDECAR + 180);
    COMP(R0, R1);
    IF NE JUMP publish_done;
    // End publishes first; matching begin is the final validity store.
    DM(238, I4) = R0;
    DM(220, I4) = R0;
publish_done:
    R0 = DM(PUBLISH_SAVE + 5);
    R1 = DM(PUBLISH_SAVE + 6);
    R2 = DM(PUBLISH_SAVE + 7);
    R3 = DM(PUBLISH_SAVE + 8);
    STKYX = DM(PUBLISH_SAVE + 3);
    STKYY = DM(PUBLISH_SAVE + 4);
    ASTATX = DM(PUBLISH_SAVE + 1);
    ASTATY = DM(PUBLISH_SAVE + 2);
    MODE1 = DM(PUBLISH_SAVE + 0);
    NOP;
    RTS (LR);

// SPDX-License-Identifier: GPL-3.0-or-later
// Scalar binary32 helpers. F0 argument/result; R0..R5 and arithmetic flags volatile.
// Math scratch is caller-private DM384..398; ADAA also owns channel18..23.
// No shared data or tables.
gh_recip:
    F1 = RECIPS F0;
    F2 = F0 * F1;
    F3 = 2.0;
    F2 = F3 - F2;
    F1 = F1 * F2;
    F2 = F0 * F1;
    F2 = F3 - F2;
    F0 = F1 * F2;
    RTS;

gh_exp:
    F1 = 1.4426950408889634;
    F1 = F0 * F1;
    R4 = TRUNC F1;
    F2 = FLOAT R4;
    F3 = 0.6931471805599453;
    F2 = F2 * F3;
    F1 = F0 - F2;
    F0 = 0.0000002755731922398589;
    F2 = 0.000002755731922398589;
    F0 = F0 * F1;
    F0 = F0 + F2;
    F2 = 0.0000248015873015873;
    F0 = F0 * F1;
    F0 = F0 + F2;
    F2 = 0.0001984126984126984;
    F0 = F0 * F1;
    F0 = F0 + F2;
    F2 = 0.001388888888888889;
    F0 = F0 * F1;
    F0 = F0 + F2;
    F2 = 0.008333333333333333;
    F0 = F0 * F1;
    F0 = F0 + F2;
    F2 = 0.041666666666666664;
    F0 = F0 * F1;
    F0 = F0 + F2;
    F2 = 0.16666666666666666;
    F0 = F0 * F1;
    F0 = F0 + F2;
    F2 = 0.5;
    F0 = F0 * F1;
    F0 = F0 + F2;
    F2 = 1.0;
    F0 = F0 * F1;
    F0 = F0 + F2;
    F0 = F0 * F1;
    F0 = F0 + F2;
    F0 = SCALB F0 BY R4;
    RTS;

// ln(x), positive normal input. Range reduction x=m*2^e,1<=m<2.
// ln(m)=2*(z+z^3/3+...+z^17/17),z=(m-1)/(m+1),abs(z)<=1/3.
gh_log:
    R4 = LSHIFT R0 BY -23;
    R5 = 255;
    R4 = R4 AND R5;
    R5 = 127;
    R4 = R4 - R5;
    F4 = FLOAT R4;
    F5 = 0.6931471805599453;
    F4 = F4 * F5;
    R5 = 0x7fffff;
    R0 = R0 AND R5;
    R5 = 0x3f800000;
    R0 = R0 OR R5;
    F5 = 1.0;
    F1 = F0 - F5;
    F0 = F0 + F5;
    F2 = RECIPS F0;
    F3 = F0 * F2;
    F5 = 2.0;
    F3 = F5 - F3;
    F2 = F2 * F3;
    F3 = F0 * F2;
    F3 = F5 - F3;
    F2 = F2 * F3;
    F1 = F1 * F2;
    F2 = F1 * F1;
    F0 = 0.058823529411764705;
    F3 = 0.06666666666666667;
    F0 = F0 * F2;
    F0 = F0 + F3;
    F3 = 0.07692307692307693;
    F0 = F0 * F2;
    F0 = F0 + F3;
    F3 = 0.09090909090909091;
    F0 = F0 * F2;
    F0 = F0 + F3;
    F3 = 0.1111111111111111;
    F0 = F0 * F2;
    F0 = F0 + F3;
    F3 = 0.14285714285714285;
    F0 = F0 * F2;
    F0 = F0 + F3;
    F3 = 0.2;
    F0 = F0 * F2;
    F0 = F0 + F3;
    F3 = 0.3333333333333333;
    F0 = F0 * F2;
    F0 = F0 + F3;
    F3 = 1.0;
    F0 = F0 * F2;
    F0 = F0 + F3;
    F0 = F0 * F1;
    F3 = 2.0;
    F0 = F0 * F3;
    F0 = F0 + F4;
    RTS;

// sin(x), source angles restricted to[-2pi,4pi]; fold to[-pi/2,pi/2].
gh_sin:
    F1 = 6.283185307179586;
    F2 = 3.141592653589793;
    COMP(F0,F2);
    IF GT F0 = F0 - F1;
    COMP(F0,F2);
    IF GT F0 = F0 - F1;
    F2 = -3.141592653589793;
    COMP(F0,F2);
    IF LT F0 = F0 + F1;
    F2 = 1.5707963267948966;
    COMP(F0,F2);
    IF LE JUMP gh_sin_fold_negative;
    F1 = 3.141592653589793;
    F0 = F1 - F0;
    JUMP gh_sin_poly;
gh_sin_fold_negative:
    F2 = -1.5707963267948966;
    COMP(F0,F2);
    IF GE JUMP gh_sin_poly;
    F1 = -3.141592653589793;
    F0 = F1 - F0;
gh_sin_poly:
    F1 = F0;
    F2 = F1 * F1;
    F0 = 0.00000000016059043836821615;
    F3 = -0.00000002505210838544172;
    F0 = F0 * F2;
    F0 = F0 + F3;
    F3 = 0.0000027557319223985893;
    F0 = F0 * F2;
    F0 = F0 + F3;
    F3 = -0.0001984126984126984;
    F0 = F0 * F2;
    F0 = F0 + F3;
    F3 = 0.008333333333333333;
    F0 = F0 * F2;
    F0 = F0 + F3;
    F3 = -0.16666666666666666;
    F0 = F0 * F2;
    F0 = F0 + F3;
    F3 = 1.0;
    F0 = F0 * F2;
    F0 = F0 + F3;
    F0 = F0 * F1;
    RTS;

gh_tan:
    DM(388,I0) = F0;
    CALL gh_sin;
    DM(389,I0) = F0;
    F0 = DM(388,I0);
    F1 = 1.5707963267948966;
    F0 = F0 + F1;
    CALL gh_sin;
    CALL gh_recip;
    F1 = DM(389,I0);
    F0 = F0 * F1;
    RTS;

// log1p(x), x>=0 (the ADAA antiderivative's abs(x)). Preserve the correction
// lost by rounding 1+x, reduce m to[sqrt(.5),sqrt(2)], and evaluate
// f - f*f/2 + s*(f*f/2 + 2*z*(1/3+z/5+...)),s=f/(2+f),z=s*s.
// Split ln(2) keeps the integer exponent product exact before its low tail is
// combined with the reduced mantissa. Private scratch384..387,390 only.
gh_log1p:
    DM(384,I0) = F0;
    F1 = 1.0;
    F0 = F0 + F1;
    DM(385,I0) = F0;
    F2 = DM(384,I0);
    COMP(F2,F1);
    IF LT JUMP gh_log1p_small_correction;
    F2 = F0 - F2;
    F2 = F1 - F2;
    JUMP gh_log1p_have_correction;
gh_log1p_small_correction:
    F3 = F0 - F1;
    F2 = F2 - F3;
gh_log1p_have_correction:
    DM(384,I0) = F2;
    CALL gh_recip;
    F1 = DM(384,I0);
    F0 = F0 * F1;
    DM(384,I0) = F0;
    R0 = DM(385,I0);
    R4 = LSHIFT R0 BY -23;
    R5 = 255;
    R4 = R4 AND R5;
    R5 = 127;
    R4 = R4 - R5;
    R5 = 0x7fffff;
    R0 = R0 AND R5;
    R5 = 0x3f800000;
    R0 = R0 OR R5;
    F1 = 1.4142135623730951;
    COMP(F0,F1);
    IF LE JUMP gh_log1p_normalized;
    F1 = 0.5;
    F0 = F0 * F1;
    R4 = R4 + 1;
gh_log1p_normalized:
    F4 = FLOAT R4;
    F5 = 0.69313812255859375;
    F5 = F4 * F5;
    DM(385,I0) = F5;
    F5 = 0.000009058000614521908;
    F4 = F4 * F5;
    F5 = DM(384,I0);
    F4 = F4 + F5;
    DM(384,I0) = F4;
    F1 = 1.0;
    F0 = F0 - F1;
    DM(386,I0) = F0;
    F1 = F0 * F0;
    F2 = 0.5;
    F1 = F1 * F2;
    DM(387,I0) = F1;
    F1 = 2.0;
    F0 = F0 + F1;
    CALL gh_recip;
    F1 = DM(386,I0);
    F0 = F0 * F1;
    DM(390,I0) = F0;
    F2 = F0 * F0;
    F0 = 0.11764705882352941;
    F3 = 0.13333333333333333;
    F0 = F0 * F2;
    F0 = F0 + F3;
    F3 = 0.15384615384615385;
    F0 = F0 * F2;
    F0 = F0 + F3;
    F3 = 0.18181818181818182;
    F0 = F0 * F2;
    F0 = F0 + F3;
    F3 = 0.2222222222222222;
    F0 = F0 * F2;
    F0 = F0 + F3;
    F3 = 0.2857142857142857;
    F0 = F0 * F2;
    F0 = F0 + F3;
    F3 = 0.4;
    F0 = F0 * F2;
    F0 = F0 + F3;
    F3 = 0.6666666666666666;
    F0 = F0 * F2;
    F0 = F0 + F3;
    F0 = F0 * F2;
    F1 = DM(387,I0);
    F0 = F0 + F1;
    F1 = DM(390,I0);
    F0 = F0 * F1;
    F1 = DM(384,I0);
    F0 = F0 + F1;
    F1 = DM(387,I0);
    F0 = F1 - F0;
    F1 = DM(386,I0);
    F0 = F0 - F1;
    F1 = DM(385,I0);
    F0 = F1 - F0;
    RTS;

// Compensated division for the ADAA normalized input. F0=a,F1=b -> a/b.
// A one-ULP input error is audible to the antiderivative's small delta even
// when the reciprocal is otherwise accurate. Recover q*b's rounding residual
// from12-significant-bit split products, then correct the quotient once.
// Positive finite denominator; private scratch391..398, all R0..R5 volatile.
gh_divide:
    DM(391,I0) = F0;
    DM(392,I0) = F1;
    F0 = F1;
    CALL gh_recip;
    DM(393,I0) = F0;
    F1 = DM(391,I0);
    F0 = F0 * F1;
    DM(394,I0) = F0;
    F1 = DM(392,I0);
    F0 = F0 * F1;
    DM(395,I0) = F0;
    R2 = DM(394,I0);
    R3 = 0xfffff000;
    R2 = R2 AND R3;
    DM(396,I0) = R2;
    F4 = DM(394,I0);
    F4 = F4 - F2;
    DM(397,I0) = F4;
    R2 = DM(392,I0);
    R2 = R2 AND R3;
    DM(398,I0) = R2;
    F5 = DM(392,I0);
    F5 = F5 - F2;
    F0 = DM(396,I0);
    F1 = DM(398,I0);
    F0 = F0 * F1;
    F2 = DM(395,I0);
    F0 = F0 - F2;
    F1 = DM(396,I0);
    F1 = F1 * F5;
    F0 = F0 + F1;
    F1 = DM(397,I0);
    F2 = DM(398,I0);
    F1 = F1 * F2;
    F0 = F0 + F1;
    F1 = DM(397,I0);
    F1 = F1 * F5;
    F0 = F0 + F1;
    F1 = DM(391,I0);
    F2 = DM(395,I0);
    F1 = F1 - F2;
    F1 = F1 - F0;
    F2 = DM(393,I0);
    F1 = F1 * F2;
    F0 = DM(394,I0);
    F0 = F0 + F1;
    RTS;

// First-order ADAA soft clip with the previous integral cached per channel.
// F0=current normalized input, I6=channel base, I0=instance -> F0=output.
// R0..R5/flags volatile; R6..R15 and all address/mode registers preserved.
// Channel4 retains the source's previous input,18 integral,19 valid,
// 20 current input,21 delta,22 current integral/midpoint,23 temporary.
// Existing log1p helper scratch384..390 remains caller-private and volatile.
// Large deltas normally need one log1p; a cold/invalidation miss needs two.
// Small deltas never calculate an integral and invalidate it only on change.
gh_adaa:
    DM(20,I6) = F0;
    F1 = DM(4,I6);
    F2 = F0 - F1;
    DM(21,I6) = F2;
    F2 = ABS F2;
    F3 = 0.001;
    COMP(F2,F3);
    IF LT JUMP gh_adaa_midpoint;

    F0 = ABS F0;
    DM(22,I6) = F0;
    CALL gh_log1p;
    F1 = DM(22,I6);
    F0 = F1 - F0;
    DM(22,I6) = F0;
    R0 = DM(19,I6);
    R0 = PASS R0;
    IF NE JUMP gh_adaa_cached;
    F0 = DM(4,I6);
    F0 = ABS F0;
    DM(23,I6) = F0;
    CALL gh_log1p;
    F1 = DM(23,I6);
    F0 = F1 - F0;
    JUMP gh_adaa_difference;
gh_adaa_cached:
    F0 = DM(18,I6);
gh_adaa_difference:
    F1 = DM(22,I6);
    DM(18,I6) = F1;
    R2 = 1;
    DM(19,I6) = R2;
    F1 = F1 - F0;
    DM(23,I6) = F1;
    F0 = DM(21,I6);
    CALL gh_recip;
    F1 = DM(23,I6);
    F0 = F1 * F0;
    JUMP gh_adaa_done;

gh_adaa_midpoint:
    // Bitwise identity lets a repeated sample retain a valid integral. Either
    // sign of zero is mathematically safe; changing its bits just invalidates.
    COMPU(R0,R1);
    IF EQ JUMP gh_adaa_midpoint_value;
    R2 = 0;
    DM(19,I6) = R2;
gh_adaa_midpoint_value:
    F0 = F0 + F1;
    F1 = 0.5;
    F0 = F0 * F1;
    DM(22,I6) = F0;
    F0 = ABS F0;
    F1 = 1.0;
    F0 = F1 + F0;
    CALL gh_recip;
    F1 = DM(22,I6);
    F0 = F1 * F0;
gh_adaa_done:
    R1 = DM(20,I6);
    DM(4,I6) = R1;
    RTS;

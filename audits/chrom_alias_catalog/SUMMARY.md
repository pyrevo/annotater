# UCSC chromAlias catalog audit (2026-10-02)

Catalog: https://api.genome.ucsc.edu/list/ucscGenomes (data time 2026-08-18T15:38:37, sha256 f8da527c7a925f62…)
Candidates: 238; with chromAlias: 132

| status | count |
|---|---|
| FAIL | 5 |
| NO_SOURCE | 106 |
| PASS | 122 |
| REVIEW | 5 |

| reason code | assemblies |
|---|---|
| ACCESSION_SHAPE | 3 |
| MULTIPLE_ALIAS_PER_AUTHORITY | 3 |
| NO_CHROM_ALIAS | 106 |
| PASS | 122 |
| SOURCE_LABEL_MISMATCH | 2 |
| UNSUPPORTED_SOURCE_LABEL | 2 |

Wide schema lossless: 129; lossy: 3
PASS assemblies: 122; TSV 530,113,948 bytes (77,414,827 deflated)

| db | status | reasons | sequences | alias rows |
|---|---|---|---|---|
| ARS_UCD2.0 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| ARS_UI_Ramb_v2.0 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| Fca126_mat1.0 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| GRCg7b | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| GRCz12ab | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| GRCz12tu | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| Inina_mat1.0 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| T2T_MFA8v1.1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| T2T_MMU8v2.0 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| TB_T2T | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| ailMel1 | PASS | PASS | 81467 | 162934 |
| allMis1 | PASS | PASS | 14645 | 29289 |
| anoCar1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| anoCar2 | PASS | PASS | 6457 | 19378 |
| anoGam1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| anoGam3 | FAIL | MULTIPLE_ALIAS_PER_AUTHORITY | 8041 | 16186 |
| apiMel1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| apiMel2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| aplCal1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| aptMan1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| aquChr2 | PASS | PASS | 1141 | 2282 |
| bTaeGut1.4 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| balAcu1 | PASS | PASS | 10776 | 21551 |
| bisBis1 | PASS | PASS | 450182 | 578614 |
| bosTau2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| bosTau3 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| bosTau4 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| bosTau6 | PASS | PASS | 3317 | 3317 |
| bosTau7 | PASS | PASS | 11691 | 11691 |
| bosTau8 | REVIEW | ACCESSION_SHAPE | 3179 | 6357 |
| bosTau9 | PASS | PASS | 2211 | 4453 |
| braFlo1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| caeJap1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| caePb1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| caePb2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| caeRem2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| caeRem3 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| calJac1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| calJac240_pri | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| calJac3 | PASS | PASS | 14205 | 28434 |
| calJac4 | PASS | PASS | 964 | 2868 |
| calMil1 | PASS | PASS | 21204 | 42408 |
| canFam1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| canFam2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| canFam3 | PASS | PASS | 3268 | 6575 |
| canFam4 | PASS | PASS | 2198 | 2198 |
| canFam5 | PASS | PASS | 794 | 1548 |
| canFam6 | PASS | PASS | 147 | 441 |
| cavPor3 | PASS | PASS | 3144 | 6288 |
| cb1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| cb3 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| ce10 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| ce11 | PASS | PASS | 7 | 14 |
| ce2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| ce4 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| ce6 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| cerSim1 | PASS | PASS | 3087 | 6173 |
| chlSab2 | PASS | PASS | 2004 | 4008 |
| choHof1 | PASS | PASS | 481259 | 927630 |
| chrPic1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| ci1 | PASS | PASS | 2501 | 2501 |
| ci2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| ci3 | PASS | PASS | 1272 | 2559 |
| criGri1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| criGriChoV1 | PASS | PASS | 109152 | 218305 |
| criGriChoV2 | PASS | PASS | 8265 | 16531 |
| danRer10 | PASS | PASS | 1061 | 2147 |
| danRer11 | PASS | PASS | 1923 | 3872 |
| danRer3 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| danRer4 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| danRer5 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| danRer6 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| danRer7 | PASS | PASS | 1133 | 1133 |
| dasNov3 | PASS | PASS | 46559 | 93117 |
| dipOrd1 | PASS | PASS | 210053 | 399135 |
| dm1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| dm2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| dm3 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| dm6 | PASS | PASS | 1870 | 5609 |
| dp2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| dp3 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| droAna1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| droAna2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| droEre1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| droGri1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| droMoj1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| droMoj2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| droPer1 | PASS | PASS | 12838 | 25676 |
| droSec1 | PASS | PASS | 14730 | 14730 |
| droSim1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| droVir1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| droVir2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| droYak1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| droYak2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| eboVir3 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| echTel1 | PASS | PASS | 288817 | 288817 |
| echTel2 | PASS | PASS | 8402 | 16803 |
| enhLutNer1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| equCab1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| equCab2 | PASS | PASS | 33 | 98 |
| equCab3 | PASS | PASS | 4701 | 9435 |
| eriEur1 | PASS | PASS | 343664 | 343664 |
| eriEur2 | PASS | PASS | 5803 | 11605 |
| felCat3 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| felCat4 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| felCat5 | PASS | PASS | 5500 | 11018 |
| felCat8 | PASS | PASS | 267625 | 535270 |
| felCat9 | PASS | PASS | 4508 | 9036 |
| fr1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| fr2 | PASS | PASS | 1 | 1 |
| fr3 | PASS | PASS | 6835 | 13693 |
| gadMor1 | PASS | PASS | 393741 | 393741 |
| galGal2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| galGal3 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| galGal4 | PASS | PASS | 15932 | 31897 |
| galGal5 | PASS | PASS | 23475 | 46985 |
| galGal6 | PASS | PASS | 464 | 963 |
| galVar1 | PASS | PASS | 179514 | 359027 |
| gasAcu1 | PASS | PASS | 22 | 22 |
| geoFor1 | PASS | PASS | 27239 | 54478 |
| gorGor3 | PASS | PASS | 25 | 25 |
| gorGor4 | FAIL | MULTIPLE_ALIAS_PER_AUTHORITY | 40692 | 81420 |
| gorGor5 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| gorGor6 | PASS | PASS | 5486 | 10972 |
| hetGla1 | PASS | PASS | 39267 | 39268 |
| hetGla2 | PASS | PASS | 4229 | 8458 |
| hg16 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| hg17 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| hg18 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| hg19 | REVIEW | SOURCE_LABEL_MISMATCH | 298 | 892 |
| hg38 | PASS | PASS | 711 | 2129 |
| hs1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| latCha1 | PASS | PASS | 22819 | 45638 |
| loxAfr3 | PASS | PASS | 2353 | 4704 |
| mCalJa1.2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| mGorGor1_v2.1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| mPanPan1_v2.0 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| mPanTro3_v2.0 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| mPonAbe1_v2.0 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| macEug2 | PASS | PASS | 277711 | 437207 |
| macFas5 | PASS | PASS | 7601 | 15224 |
| manPen1 | REVIEW | ACCESSION_SHAPE | 92770 | 92770 |
| melGal1 | PASS | PASS | 5890 | 11812 |
| melGal5 | PASS | PASS | 231286 | 462572 |
| melUnd1 | PASS | PASS | 25212 | 50424 |
| micMur1 | PASS | PASS | 185042 | 185042 |
| micMur2 | PASS | PASS | 10311 | 20622 |
| mm10 | PASS | PASS | 239 | 717 |
| mm39 | PASS | PASS | 61 | 183 |
| mm7 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| mm8 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| mm9 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| monDom1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| monDom4 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| monDom5 | PASS | PASS | 11 | 30 |
| mpxvRivers | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| musFur1 | PASS | PASS | 7741 | 7741 |
| nanPar1 | PASS | PASS | 25187 | 50374 |
| nasLar1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| neoSch1 | PASS | PASS | 7872 | 15744 |
| nomLeu1 | PASS | PASS | 17968 | 17968 |
| nomLeu2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| nomLeu3 | PASS | PASS | 17492 | 35002 |
| ochPri2 | PASS | PASS | 187558 | 375116 |
| ochPri3 | PASS | PASS | 10420 | 20839 |
| oreNil2 | PASS | PASS | 5678 | 11356 |
| ornAna1 | PASS | PASS | 201523 | 602922 |
| ornAna2 | PASS | PASS | 201525 | 602923 |
| oryCun2 | PASS | PASS | 3242 | 3242 |
| oryLat2 | PASS | PASS | 7189 | 7189 |
| otoGar3 | PASS | PASS | 7793 | 15586 |
| oviAri1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| oviAri3 | PASS | PASS | 5698 | 11423 |
| oviAri4 | PASS | PASS | 5466 | 10932 |
| panPan1 | PASS | PASS | 10867 | 21733 |
| panPan2 | PASS | PASS | 10274 | 20573 |
| panPan3 | FAIL | UNSUPPORTED_SOURCE_LABEL | 4293 | 12857 |
| panTro1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| panTro2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| panTro3 | PASS | PASS | 24127 | 24127 |
| panTro4 | PASS | PASS | 24129 | 48283 |
| panTro5 | PASS | PASS | 44449 | 88924 |
| panTro6 | REVIEW | SOURCE_LABEL_MISMATCH | 4346 | 8691 |
| papAnu2 | PASS | PASS | 63250 | 126521 |
| papAnu4 | PASS | PASS | 63235 | 126490 |
| papHam1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| petMar1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| petMar2 | PASS | PASS | 25006 | 25006 |
| petMar3 | PASS | PASS | 12062 | 12063 |
| ponAbe2 | PASS | PASS | 55 | 55 |
| ponAbe3 | PASS | PASS | 5261 | 10522 |
| priPac1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| proCap1 | PASS | PASS | 295006 | 564390 |
| pteVam1 | PASS | PASS | 96944 | 183484 |
| rheMac10 | PASS | PASS | 2939 | 5878 |
| rheMac2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| rheMac3 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| rheMac8 | PASS | PASS | 284728 | 569478 |
| rhiRox1 | PASS | PASS | 135512 | 271025 |
| rn3 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| rn4 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| rn5 | PASS | PASS | 155 | 155 |
| rn6 | FAIL | MULTIPLE_ALIAS_PER_AUTHORITY | 953 | 1933 |
| rn7 | PASS | PASS | 176 | 528 |
| rn8 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| sacCer1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| sacCer2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| sacCer3 | PASS | PASS | 17 | 51 |
| saiBol1 | PASS | PASS | 2685 | 5370 |
| sarHar1 | PASS | PASS | 35974 | 71948 |
| sorAra1 | PASS | PASS | 235768 | 235768 |
| sorAra2 | PASS | PASS | 12845 | 25690 |
| speTri2 | PASS | PASS | 12483 | 24966 |
| strPur1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| strPur2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| susScr11 | PASS | PASS | 613 | 1247 |
| susScr2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| susScr3 | PASS | PASS | 4583 | 9186 |
| taeGut1 | PASS | PASS | 70 | 70 |
| taeGut2 | PASS | PASS | 37096 | 74191 |
| tarSyr1 | PASS | PASS | 622647 | 622647 |
| tarSyr2 | PASS | PASS | 337189 | 674379 |
| tetNig1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| tetNig2 | PASS | PASS | 27 | 27 |
| thaSir1 | REVIEW | ACCESSION_SHAPE | 7930 | 15860 |
| triMan1 | PASS | PASS | 6323 | 12645 |
| tupBel1 | PASS | PASS | 131600 | 131600 |
| turTru2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| vicPac1 | PASS | PASS | 287207 | 287207 |
| vicPac2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| wuhCor1 | PASS | PASS | 1 | 2 |
| xenLae2 | PASS | PASS | 108033 | 216066 |
| xenTro1 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| xenTro10 | PASS | PASS | 167 | 501 |
| xenTro2 | NO_SOURCE | NO_CHROM_ALIAS |  |  |
| xenTro3 | PASS | PASS | 19550 | 19550 |
| xenTro7 | PASS | PASS | 7728 | 15455 |
| xenTro9 | FAIL | UNSUPPORTED_SOURCE_LABEL | 6822 | 20476 |

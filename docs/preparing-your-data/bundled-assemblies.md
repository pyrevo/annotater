# Bundled genome assemblies

These are the genome assemblies whose chromosome registries ship with
AnnotateR. Choose one in the sidebar's **Genome assembly** selector to
normalize chromosome identifiers
([how it works](chromosome-identifiers.md)); for any other assembly use a
[custom chromosome mapping](chromosome-identifiers.md#custom-chromosome-mapping).

A bundled registry lets AnnotateR normalize the verified identifiers
present in that registry. Some registries are narrow (a few UCSC databases
list only a handful of sequences in the authoritative alias source), and
no registry offers a name in every naming system for every sequence. See
[Chromosome registries: provenance and audit](../technical/chromosome-registry.md)
for how the list was chosen and how much each naming system is covered.

This page is generated from the catalog that ships with the application
(`python scripts/generate_assembly_docs.py`), so it always matches the
release.

<!-- BEGIN CATALOG: bundled_assemblies -->
64 genome assemblies of 46 species are bundled in this release, listed here in the order of the **Genome assembly** selector. The selector label is what you choose in the application; the AnnotateR id and the UCSC database id are the names used for the same assembly elsewhere, and both are accepted wherever an assembly id is accepted.

| Organism | Scientific name | Selector label | AnnotateR id | UCSC database |
|---|---|---|---|---|
| Bushbaby | Otolemur garnettii | Bushbaby — Mar. 2011 (Broad/otoGar3) | otoGar3 | otoGar3 |
| C. elegans | Caenorhabditis elegans | C. elegans — Feb. 2013 (WBcel235/ce11) | WBcel235 | ce11 |
| C. intestinalis | Ciona intestinalis | C. intestinalis — Dec. 2002 (JGI 1.0/ci1) | ci1 | ci1 |
| C. intestinalis | Ciona intestinalis | C. intestinalis — Apr. 2011 (Kyoto KH/ci3) | ci3 | ci3 |
| Cat | Felis catus | Cat — Sep. 2011 (ICGSC Felis_catus 6.2/felCat5) | felCat5 | felCat5 |
| Cat | Felis catus | Cat — Nov. 2017 (Felis_catus_9.0/felCat9) | Felis_catus_9.0 | felCat9 |
| Chicken | Gallus gallus | Chicken — Mar. 2018 (GRCg6a/galGal6) | GRCg6a | galGal6 |
| Chinese hamster | Cricetulus griseus | Chinese hamster — Jun. 2017 (CHOK1S_HZDv1/criGriChoV2) | criGriChoV2 | criGriChoV2 |
| Cow | Bos taurus | Cow — Nov. 2009 (Bos_taurus_UMD_3.1/bosTau6) | bosTau6 | bosTau6 |
| Cow | Bos taurus | Cow — Apr. 2018 (ARS-UCD1.2/bosTau9) | ARS-UCD1.2 | bosTau9 |
| Crab-eating macaque | Macaca fascicularis | Crab-eating macaque — Jun. 2013 (Macaca_fascicularis_5.0/macFas5) | macFas5 | macFas5 |
| D. melanogaster | Drosophila melanogaster | D. melanogaster — Aug. 2014 (BDGP Release 6 + ISO1 MT/dm6) | dm6 | dm6 |
| Dog | Canis lupus familiaris | Dog — Sep. 2011 (Broad CanFam3.1/canFam3) | canFam3 | canFam3 |
| Dog | Canis lupus familiaris | Dog — Mar. 2020 (UU_Cfam_GSD_1.0/canFam4) | UU_Cfam_GSD_1.0 | canFam4 |
| Dog | Canis lupus familiaris | Dog — May 2019 (UMICH_Zoey_3.1/canFam5) | canFam5 | canFam5 |
| Dog | Canis lupus familiaris | Dog — Oct. 2020 (Dog10K_Boxer_Tasha/canFam6) | canFam6 | canFam6 |
| Elephant | Loxodonta africana | Elephant — Jul. 2009 (Broad/loxAfr3) | loxAfr3 | loxAfr3 |
| Ferret  | Mustela putorius furo | Ferret — Apr. 2011 (MusPutFur1.0/musFur1) | musFur1 | musFur1 |
| Fugu | Takifugu rubripes | Fugu — Oct. 2004 (JGI 4.0/fr2) | fr2 | fr2 |
| Fugu | Takifugu rubripes | Fugu — Oct. 2011 (FUGU5/fr3) | fr3 | fr3 |
| Golden eagle | Aquila chrysaetos canadensis | Golden eagle — Oct. 2014 (aquChr-1.0.2/aquChr2) | aquChr2 | aquChr2 |
| Gorilla | Gorilla gorilla gorilla | Gorilla — May 2011 (gorGor3.1/gorGor3) | gorGor3 | gorGor3 |
| Gorilla | Gorilla gorilla gorilla | Gorilla — Aug. 2019 (Kamilah_GGO_v0/gorGor6) | gorGor6 | gorGor6 |
| Green monkey | Chlorocebus sabaeus | Green monkey — Mar. 2014 (Chlorocebus_sabeus 1.1/chlSab2) | chlSab2 | chlSab2 |
| Guinea pig | Cavia porcellus | Guinea pig — Feb. 2008 (Broad/cavPor3) | cavPor3 | cavPor3 |
| Hawaiian monk seal | Neomonachus schauinslandi | Hawaiian monk seal — Jun. 2017 (ASM220157v1/neoSch1) | neoSch1 | neoSch1 |
| Hedgehog | Erinaceus europaeus | Hedgehog — May 2012 (EriEur2.0/eriEur2) | eriEur2 | eriEur2 |
| Horse | Equus caballus | Horse — Sep. 2007 (Broad/equCab2) | equCab2 | equCab2 |
| Horse | Equus caballus | Horse — Jan. 2018 (EquCab3.0/equCab3) | EquCab3.0 | equCab3 |
| Human | Homo sapiens | Human — Feb. 2009 (GRCh37/hg19) | hg19 | hg19 |
| Human | Homo sapiens | Human — Dec. 2013 (GRCh38/hg38) | GRCh38 | hg38 |
| Lizard | Anolis carolinensis | Lizard — May 2010 (Broad AnoCar2.0/anoCar2) | anoCar2 | anoCar2 |
| Manatee | Trichechus manatus latirostris | Manatee — Oct. 2011 (Broad v1.0/triMan1) | triMan1 | triMan1 |
| Marmoset | Callithrix jacchus | Marmoset — May 2020 (Callithrix_jacchus_cj1700_1.1/calJac4) | calJac4 | calJac4 |
| Medaka | Oryzias latipes | Medaka — Oct. 2005 (NIG/UT MEDAKA1/oryLat2) | oryLat2 | oryLat2 |
| Mouse | Mus musculus | Mouse — Dec. 2011 (GRCm38/mm10) | GRCm38 | mm10 |
| Mouse | Mus musculus | Mouse — Jun. 2020 (GRCm39/mm39) | GRCm39 | mm39 |
| Naked mole-rat | Heterocephalus glaber | Naked mole-rat — Jan. 2012 (Broad HetGla_female_1.0/hetGla2) | hetGla2 | hetGla2 |
| Nile tilapia | Oreochromis niloticus | Nile tilapia — Jan. 2011 (Broad oreNil1.1/oreNil2) | oreNil2 | oreNil2 |
| Opossum | Monodelphis domestica | Opossum — Oct. 2006 (Broad/monDom5) | monDom5 | monDom5 |
| Orangutan | Pongo pygmaeus abelii | Orangutan — July 2007 (WUGSC 2.0.2/ponAbe2) | ponAbe2 | ponAbe2 |
| Orangutan | Pongo pygmaeus abelii | Orangutan — Jan. 2018 (Susie_PABv2/ponAbe3) | ponAbe3 | ponAbe3 |
| Pig | Sus scrofa | Pig — Feb. 2017 (Sscrofa11.1/susScr11) | Sscrofa11.1 | susScr11 |
| Pig | Sus scrofa | Pig — Aug. 2011 (SGSC Sscrofa10.2/susScr3) | susScr3 | susScr3 |
| Rabbit | Oryctolagus cuniculus | Rabbit — Apr. 2009 (Broad/oryCun2) | oryCun2 | oryCun2 |
| Rat | Rattus norvegicus | Rat — Mar. 2012 (RGSC 5.0/rn5) | rn5 | rn5 |
| Rat | Rattus norvegicus | Rat — Nov. 2020 (mRatBN7.2/rn7) | mRatBN7.2 | rn7 |
| Rhesus | Macaca mulatta | Rhesus — Feb. 2019 (Mmul_10/rheMac10) | Mmul_10 | rheMac10 |
| S. cerevisiae | Saccharomyces cerevisiae | S. cerevisiae — Apr. 2011 (SacCer_Apr2011/sacCer3) | sacCer3 | sacCer3 |
| SARS-CoV-2 | SARS-CoV-2 | SARS-CoV-2 — Jan. 2020 (NC_045512.2) [wuhCor1] | wuhCor1 | wuhCor1 |
| Sheep | Ovis aries | Sheep — Aug. 2012 (ISGC Oar_v3.1/oviAri3) | oviAri3 | oviAri3 |
| Sheep | Ovis aries | Sheep — Nov. 2015 (Oar_v4.0/oviAri4) | Oar_v4.0 | oviAri4 |
| Squirrel monkey | Saimiri boliviensis | Squirrel monkey — Oct. 2011 (Broad/saiBol1) | saiBol1 | saiBol1 |
| Stickleback | Gasterosteus aculeatus | Stickleback — Feb. 2006 (Broad/gasAcu1) | gasAcu1 | gasAcu1 |
| Tenrec | Echinops telfairi | Tenrec — Nov. 2012 (Broad/echTel2) | echTel2 | echTel2 |
| Tetraodon | Tetraodon nigroviridis | Tetraodon — Mar. 2007 (Genoscope 8.0/tetNig2) | tetNig2 | tetNig2 |
| Turkey | Meleagris gallopavo | Turkey — Dec. 2009 (TGC Turkey_2.01/melGal1) | melGal1 | melGal1 |
| White rhinoceros | Ceratotherium simum | White rhinoceros — May 2012 (CerSimSim1.0/cerSim1) | cerSim1 | cerSim1 |
| X. tropicalis | Xenopus tropicalis | X. tropicalis — Nov. 2019 (UCB_Xtro_10.0/xenTro10) | xenTro10 | xenTro10 |
| X. tropicalis | Xenopus tropicalis | X. tropicalis — Sep. 2012 (JGI 7.0/xenTro7) | xenTro7 | xenTro7 |
| Zebra finch | Taeniopygia guttata | Zebra finch — Jul. 2008 (WUGSC 3.2.4/taeGut1) | taeGut1 | taeGut1 |
| Zebrafish | Danio rerio | Zebrafish — Sep. 2014 (GRCz10/danRer10) | GRCz10 | danRer10 |
| Zebrafish | Danio rerio | Zebrafish — May 2017 (GRCz11/danRer11) | GRCz11 | danRer11 |
| Zebrafish | Danio rerio | Zebrafish — Jul. 2010 (Zv9/danRer7) | danRer7 | danRer7 |
<!-- END CATALOG: bundled_assemblies -->

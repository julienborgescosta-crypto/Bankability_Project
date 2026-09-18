# Termes de financement et de frais des projets synthétiques dans un fichier de config

Les projets du Configurateur (portefeuille v2) sont construits combinatoirement depuis `AU_Store`
+ `COPEX_library`, sans classeur `I-Project` réel derrière eux — contrairement au flux mono-projet
existant qui lit ces termes (marge senior, swap, upfront fee, tiering DSCR sécurisé/merchant,
maturité 10 ans merchant / PPA+3 ans, mécanisme de frais d'agrégateur avant/après seuil) dans un
vrai `I-Project`. Décision : ces termes deviennent des défauts dans un nouveau fichier
`config/aur_financing_terms.yaml` (même pattern que `risk_thresholds.yaml`), calibrés sur le
projet `I-Project` réel validé (marge senior 150 bps, swap +10 bps, upfront 130 bps, DSCR 1,20
sécurisé/1,40 merchant, maturité 10 ans merchant/PPA+3 ans, frais d'agrégateur avant/après seuil
avec bascules net-des-coûts-d'énergie/net-du-TURPE), overridables par projet dans le
Configurateur. Rejeté : les coder en dur en Python (plus dur à ajuster sans toucher au code), ou
exiger un classeur `I-Project` réel par projet synthétique (contredit l'objet même du
Configurateur combinatoire).

# La marge de la stratégie « développer & vendre au RtB » se décompose en DSA fixe + SPA résolu

La stratégie 1 a besoin d'une marge de dev captée par QEF (repère marché 50-100 k€/MW cité dans le
brief). Décision, reprise de la méthodologie Optimus (PV) de QEnergy : le prix payé par l'acheteur
RtB se décompose en deux legs — **DSA**, un montant **fixe négocié** (défaut 100 k€/MW, overridable
par projet), financable par dette (rejoint l'assiette « Total Uses » gearée comme les ajouts
DSRA/frais de financement déjà gérés pour le CAPEX) ; et **SPA**, le complément de prix qui ramène
le TRI equity réel de l'acheteur (calculé sur des cashflows incluant déjà le DSA) exactement à son
TRI cible — un solve unique de type NPV/TRI-cible, mathématiquement identique à
`acquisition.py` (`NPV(TRI cible, cashflows equity) - investissement equity requis`), pas une
boucle itérative sur DSA. **TSP = DSA + SPA** est le revenu total affiché pour cette stratégie.
SPA peut être négatif (DSA trop élevé pour la rentabilité du projet) sans que TSP le soit
forcément — afficher les deux composantes, jamais seulement leur somme. Rejeté : faire de DSA la
variable résolue par une boucle de convergence vers une cible de marge globale (plus complexe,
et le brief confirme que dans la méthodologie source, seul SPA varie une fois DSA fixé).

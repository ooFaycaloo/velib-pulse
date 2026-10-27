# Évaluation de la détection d'incidents

5 simulations × 150 stations × 48 h, 10 incidents injectés par simulation (3 stations muettes, 2 pannes de bornettes, 1 fermeture, 2 stations toujours vides, 2 toujours pleines).

- **Rappel : 100%** (50/50 incidents retrouvés)
- **Précision : 100%** (0 fausse(s) alerte(s))

| Type | Détectés | Manqués | Fausses alertes | Écart médian sur l'heure de début |
|---|---|---|---|---|
| STALE_DATA | 15 | 0 | 0 | 1 min |
| DOCKS_UNAVAILABLE | 10 | 0 | 0 | 14 min |
| OUT_OF_SERVICE | 5 | 0 | 0 | 5 min |
| CHRONIC_EMPTY | 10 | 0 | 0 | n/a (fenêtre 24 h) |
| CHRONIC_FULL | 10 | 0 | 0 | n/a (fenêtre 24 h) |

| Graine | Détectés | Manqués | Fausses alertes |
|---|---|---|---|
| 1 | 10 | 0 | 0 |
| 2 | 10 | 0 | 0 |
| 3 | 10 | 0 | 0 |
| 4 | 10 | 0 | 0 |
| 5 | 10 | 0 | 0 |

Limite : les données sont simulées, avec des signaux plus nets que le flux réel. Les seuils (`dbt_project.yml`, section `vars`) sont à recalibrer sur quelques semaines de données réelles.

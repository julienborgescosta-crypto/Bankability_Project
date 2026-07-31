# Bankability_Project

Outil de bancabilite pour projets de stockage batterie (BESS) : lecture du Business Plan Excel
d'un projet, moteur financier (IRR/NPV/DSCR), scenarios Bear/Base/Bull, sensibilite, stress-test
et dashboard de risques.

Le code applicatif vit dans [`bankability_app/`](bankability_app/README.md) — c'est la que se
trouvent l'app Streamlit, les tests, les specs et la documentation technique complete.

```bash
cd bankability_app
py -m streamlit run app.py
```

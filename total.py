import pandas as pd
import requests
from flask import Flask, render_template, request

app = Flask(__name__)

# Prix TTC pour chaque puissance installée (en euros)
PRIX_INSTALLATIONS = {
    3: 12900,
    4: 16900,
    5: 17900,
    6: 20900,
    7: 22900,
    8: 23900,
    9: 25900,
    10: 27900,
    12: 29900,
}

# Tableau du TAEG en fonction du nombre de mensualités
TAEG_TABLE = {
    72: 6.0603,
    84: 5.9547,
    96: 5.876,
    108: 5.8142,
    120: 5.7656,
    132: 5.7247,
    144: 5.6915,
    156: 5.6638,
    168: 5.639,
    180: 5.618,
}

def calcul_mensualites(montant, mensualites):
    """Calcule la mensualité pour un montant donné et un nombre de mensualités en utilisant le TAEG."""
    if mensualites not in TAEG_TABLE:
        return None  # Si le nombre de mensualités n'est pas dans le tableau, retourne None

    taux_annuel = TAEG_TABLE[mensualites] / 100
    taux_mensuel = taux_annuel / 12
    return round(montant * taux_mensuel / (1 - (1 + taux_mensuel) ** -mensualites), 2)

def calcul_cout_reel(prix_ttc, puissance_kwc, type_branchement):
    """Calcule le coût réel après TVA et prime."""
    if puissance_kwc > 3:
        montant_ht = prix_ttc / 1.2
        tva = round(prix_ttc - montant_ht)
    else:
        montant_ht = prix_ttc
        tva = 0

    if puissance_kwc <= 3:
        prime = 220 * puissance_kwc
    else:
        prime_kwc = min(puissance_kwc, 6) if type_branchement == 'monophase' else puissance_kwc
        prime = 160 * prime_kwc

    cout_reel =round( montant_ht - prime)
    
    return cout_reel, tva, prime

def calcul_tableau_economies(production_1kwc, puissance_kwc, cout_reel, taux_augmentation=5, prix_kwh=0.23):
    production_annuelle = production_1kwc * puissance_kwc
    economie_annuelle = round(production_annuelle * prix_kwh, 2)

    annees = 0
    economies_cumulees = 0

    while economies_cumulees < cout_reel:
        annees += 1
        economies_cumulees = round(economies_cumulees + economie_annuelle, 2)
        economie_annuelle = round(economie_annuelle * (1 + taux_augmentation / 100), 2)

    economie_mensuelle_moyenne = round(economies_cumulees / (annees * 12), 2)
    return economies_cumulees, economie_mensuelle_moyenne, annees

def trouver_installation(puissance_kwc, productible, type_branchement):
    """Trouve les détails d'une installation spécifique."""
    prix_ttc = PRIX_INSTALLATIONS[puissance_kwc]
    cout_reel, tva, prime = calcul_cout_reel(prix_ttc, puissance_kwc, type_branchement)
    economies_cumulees, economie_mensuelle_moyenne, annees = calcul_tableau_economies(
        productible, puissance_kwc, cout_reel
    )

    mensualites_options = {}
    for mensualite in TAEG_TABLE.keys():
        mensualites_options[mensualite] = {
            "prix_ttc": calcul_mensualites(prix_ttc, mensualite),
            "cout_reel": calcul_mensualites(cout_reel, mensualite)
        }

    return {
        "puissance": puissance_kwc,
        "prix_ttc": prix_ttc,
        "cout_reel": cout_reel,
        "tva": tva,
        "prime": prime,
        "economies_cumulees": economies_cumulees,
        "economie_mensuelle_moyenne": economie_mensuelle_moyenne,
        "annees": annees,
        "mensualites_options": mensualites_options,
    }

def trouver_meilleure_installation(productible, depense_mensuelle_max, type_branchement):
    """Trouve l'installation optimale et l'installation juste en dessous."""
    meilleure_installation = None
    installation_inférieure = None

    for puissance_kwc in sorted(PRIX_INSTALLATIONS):
        installation = trouver_installation(puissance_kwc, productible, type_branchement)

        if installation["economie_mensuelle_moyenne"] <= depense_mensuelle_max:
            installation_inférieure = meilleure_installation
            meilleure_installation = installation

    return meilleure_installation, installation_inférieure

@app.route('/', methods=['GET', 'POST'])
def index():
    """Affiche le formulaire de recherche."""
    if request.method == 'POST':
        postal_code = request.form['postal_code']
        cities = get_cities_from_postal_code(postal_code)
        if not cities:
            return render_template('index.html', error="Aucune ville trouvée pour ce code postal.")
        return render_template('index.html', cities=cities, postal_code=postal_code)
    return render_template('index.html')

@app.route('/calculate', methods=['POST'])
def calculate():
    """Calcule et affiche les résultats."""
    ville = request.form['selected_city']
    aspect = request.form['aspect']
    depense_mensuelle_max = float(request.form['depense_mensuelle_max'])
    type_branchement = request.form['type_branchement']

    lat, lon = get_coordinates_from_gisco(ville)
    if not lat or not lon:
        return render_template('result.html', error="Impossible de récupérer les coordonnées.")

    aspect_value = 0 if aspect == "SUD" else -90 if aspect == "EST" else 90 if aspect == "OUEST" else -45 if aspect == "SUD-EST" else 45 if aspect == "SUD-OUEST" else None
    print("Valeur d'orientation (aspect_value) :", aspect_value)
    productible = get_productible(lat, lon, aspect_value)
    if not productible:
        return render_template('result.html', error="Impossible de calculer le productible.")

    meilleure_installation, installation_inférieure = trouver_meilleure_installation(
        productible, depense_mensuelle_max, type_branchement
    )

    return render_template(
        'result.html',
        ville=ville, lat=lat, lon=lon, aspect=aspect, productible=productible,
        meilleure_installation=meilleure_installation,
        installation_inférieure=installation_inférieure,
        depense_mensuelle_max=depense_mensuelle_max  # Envoi de la dépense au template
    )

def get_cities_from_postal_code(postal_code):
    """Récupère les villes à partir du code postal via l'API Zippopotamus."""
    url = f"http://api.zippopotam.us/fr/{postal_code}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return [place['place name'] for place in data['places']]
    return None

def get_coordinates_from_gisco(city_name):
    """Récupère les coordonnées d'une ville via l'API GISCO."""
    url = f"https://gisco-services.ec.europa.eu/api?lang=en&limit=1&q={city_name}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        try:
            coordinates = data["features"][0]["geometry"]["coordinates"]
            lon, lat = coordinates[0], coordinates[1]
            return lat, lon
        except (IndexError, KeyError):
            return None, None
    return None, None

def get_productible(lat, lon, aspect_value):
    """Calcul du productible via l'API PVGIS."""
    url = (
        f"https://re.jrc.ec.europa.eu/api/v5_2/PVcalc?outputformat=basic&lat={lat}"
        f"&lon={lon}&raddatabase=PVGIS-SARAH2&peakpower=1&loss=14&pvtechchoice=crystSi"
        f"&angle=35&aspect={aspect_value}&usehorizon=1"
    )  # Fermeture de la parenthèse ici
    response = requests.get(url)
    if response.status_code == 200:
        for line in response.text.split('\n'):
            if "Year" in line:
                return float(line.split('\t')[1])
    return None

if __name__ == '__main__':
    app.run(debug=True)

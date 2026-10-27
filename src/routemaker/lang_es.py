"""Spanish (US) for the route's sentences, by the English they translate (`routemaker.lang`).

Drafted by Claude for review by a native speaker before it is relied on, the turn phrases
above all. Formal "usted", as the app's own Spanish (frontend/src/i18n/es.ts), and the same
words for the same things: "Gire ligeramente" for a bear, "Manténgase" only to stay on a way
at a fork, "con mucho tráfico" for busy. Units stay as the app writes them (mi, km, ft, m);
LTS and Avoid are the ratings' names. tests/test_lang.py checks every phrase the code passes
is here, with the same {places}.
"""

ES: dict[str, str] = {
    # ---- Turns (describe._ONTO, _STAY, _THEN_ONTO, _ON) ----
    "Left onto {street}": "Gire a la izquierda hacia {street}",
    "Right onto {street}": "Gire a la derecha hacia {street}",
    "Bear left onto {street}": "Gire ligeramente a la izquierda hacia {street}",
    "Bear right onto {street}": "Gire ligeramente a la derecha hacia {street}",
    "Left to stay on {street}": "Gire a la izquierda para seguir en {street}",
    "Right to stay on {street}": "Gire a la derecha para seguir en {street}",
    "Bear left to stay on {street}": "Manténgase a la izquierda para seguir en {street}",
    "Bear right to stay on {street}": "Manténgase a la derecha para seguir en {street}",
    ", then left onto {street}": ", luego gire a la izquierda hacia {street}",
    ", then right onto {street}": ", luego gire a la derecha hacia {street}",
    ", then bear left onto {street}": ", luego gire ligeramente a la izquierda hacia {street}",
    ", then bear right onto {street}": ", luego gire ligeramente a la derecha hacia {street}",
    "left on {street}": "a la izquierda por {street}",
    "right on {street}": "a la derecha por {street}",
    "bear left on {street}": "ligeramente a la izquierda por {street}",
    "bear right on {street}": "ligeramente a la derecha por {street}",
    ", then {listed}": ", luego {listed}",
    " and ": " y ",
    " and {count} more": " y {count} más",
    " and 1 more turn": " y 1 giro más",
    " and {count} more turns": " y {count} giros más",
    "Continue onto {street}": "Continúe por {street}",
    "Continue on {street}": "Siga por {street}",
    "Cross {road}": "Cruce {road}",
    "Take the {nth} exit onto {street} at {circle}": (
        "Tome la {nth} salida hacia {street} en {circle}"
    ),
    "the roundabout": "la rotonda",
    # ---- Where: miles first, metric in brackets ----
    "{mi} to {mi_end} mi ({km} to {km_end} km)": "{mi} a {mi_end} mi ({km} a {km_end} km)",
    "{mi} mi ({km} km), for {ft} ft ({m} m)": "{mi} mi ({km} km), por {ft} ft ({m} m)",
    "at {mi} mi ({km} km)": "en {mi} mi ({km} km)",
    # ---- Stress, facility, surface (the legend's words) ----
    "low stress (LTS 1)": "estrés bajo (LTS 1)",
    "fairly low stress (LTS 2)": "estrés bastante bajo (LTS 2)",
    "busy road (LTS 3)": "calle con mucho tráfico (LTS 3)",
    "heavy traffic (LTS 4)": "tráfico pesado (LTS 4)",
    "Avoid (legal, but best avoided)": "Avoid (permitido, pero mejor evitarlo)",
    "stress not rated": "estrés sin calificar",
    "traffic-free path": "sendero sin tráfico",
    "traffic-free": "sin tráfico",
    "protected bike lane": "carril bici protegido",
    "painted bike lane": "carril bici pintado",
    "unpaved": "sin pavimentar",
    "partly unpaved": "parcialmente sin pavimentar",
    "no street details for this part of the route, stress not rated.": (
        "sin detalles de las calles en esta parte de la ruta, estrés sin calificar."
    ),
    # ---- Junctions ----
    " at a signal": " en un semáforo",
    " at a stop sign": " en una señal de alto",
    " at an all-way stop": " en un alto en todas las direcciones",
    " where cross traffic stops": " donde se detiene el tráfico que cruza",
    ", flashing light, not a signal": ", luz intermitente, no es un semáforo",
    ", no signal mapped": ", sin semáforo en el mapa",
    " (Higher stress junction)": " (intersección de estrés más alto)",
    " (Very high stress junction)": " (intersección de estrés muy alto)",
    " (Higher stress junctions)": " (intersecciones de estrés más alto)",
    " (Very high stress junctions)": " (intersecciones de estrés muy alto)",
    "At {where}: {said}.": "En {where}: {said}.",
    "Cross {what}": "Cruce {what}",
    "Cross a slip lane off {what}": "Cruce un carril de giro de {what}",
    "Left turn across {what}": "Giro a la izquierda cruzando {what}",
    "Right turn off {what}": "Giro a la derecha saliendo de {what}",
    "Left turn onto {what}": "Giro a la izquierda hacia {what}",
    "Right turn onto {what}": "Giro a la derecha hacia {what}",
    "Join {what}": "Incorpórese a {what}",
    "Pass side streets along {what}": "Pase calles laterales a lo largo de {what}",
    "Pass a junction with {what}": "Pase una intersección con {what}",
    "a busy road": "una calle con mucho tráfico",
    "{count} crossings with traffic signals": "{count} cruces con semáforo",
    ", 1 of them a heavy-traffic road (LTS 4)": ", 1 de ellos una calle de tráfico pesado (LTS 4)",
    ", all of them heavy-traffic roads (LTS 4)": ", todos ellos calles de tráfico pesado (LTS 4)",
    ", {count} of them heavy-traffic roads (LTS 4)": (
        ", {count} de ellos calles de tráfico pesado (LTS 4)"
    ),
    # ---- Stops and walks ----
    "Stop {number} at {where}.": "Parada {number} en {where}.",
    "At {where}: walk your bike here, for {ft} ft ({m} m).": (
        "En {where}: camine con su bicicleta aquí, por {ft} ft ({m} m)."
    ),
    "the busy road": "la calle con mucho tráfico",
    "At {where}: walk your bike on the sidewalk along {road} for {distance}, about {minutes}"
    " min. The road is too busy to ride.": (
        "En {where}: camine con su bicicleta por la acera junto a {road} durante {distance},"
        " unos {minutes} min. La calle tiene demasiado tráfico para circular."
    ),
    # ---- Road hazards (core.route_hazards) ----
    "Cobblestones": "Adoquines",
    "Rails in the road": "Rieles en la calle",
    "bumpy, and slippery when wet": "irregulares y resbaladizos cuando están mojados",
    "cross them square on, a wheel can drop into the groove": (
        "crúcelos en ángulo recto, una rueda puede caer en la ranura"
    ),
    "{what} on {road}, {where}: {why}.": "{what} en {road}, {where}: {why}.",
    "an unnamed road": "una calle sin nombre",
    # ---- Climbs (core.hillseek) ----
    "Hors catégorie (HC) climb": "Subida de categoría especial (HC)",
    "Category {category} climb": "Subida de categoría {category}",
    "{n} mile": "{n} milla",
    "{n} miles": "{n} millas",
    "{name}, {mi} ({km} km) at {grade}%, {gain} gained": (
        "{name}, {mi} ({km} km) al {grade}%, {gain} de desnivel"
    ),
    "At {where}: {climb}, to the summit at {summit}.": (
        "En {where}: {climb}, hasta la cima en {summit}."
    ),
    " Mostly unpaved.": " Mayormente sin pavimentar.",
    # ---- Steep grades (routemaker.steep_grades) ----
    "Very steep uphill, up to {pct}%, for {length}.": (
        "Subida muy empinada, hasta el {pct}%, por {length}."
    ),
    "Very steep downhill, up to {pct}%, for {length}.": (
        "Bajada muy empinada, hasta el {pct}%, por {length}."
    ),
    "Steep uphill, up to {pct}%, for {length}.": "Subida empinada, hasta el {pct}%, por {length}.",
    "Steep downhill, up to {pct}%, for {length}.": (
        "Bajada empinada, hasta el {pct}%, por {length}."
    ),
    # ---- Avoid-rated junctions (routemaker.avoid_junctions) ----
    "Avoid-rated junction ahead at {where}": (
        "Intersección calificada Avoid más adelante en {where}"
    ),
    "Riding through it is a really bad idea. Please reconsider your route.": (
        "Pasar por ella es una muy mala idea. Por favor, reconsidere su ruta."
    ),
    # ---- Work zones and closures (routemaker.workzones) ----
    "The road": "La calle",
    " on {road}": " en {road}",
    "{road} marked closed ahead.": "Cierre más adelante en {road}.",
    "{road} has every lane closed ahead; bike access unclear.": (
        "{road} tiene todos los carriles cerrados más adelante; no está claro si pueden pasar"
        " bicicletas."
    ),
    "Bike lane blocked ahead{on}.": "Carril bici bloqueado más adelante{on}.",
    "Heads-up": "Aviso",
    "Work zone ahead": "Zona de obras más adelante",
    "Source: {source}.": "Fuente: {source}.",
    "Source: {source}, through {date}.": "Fuente: {source}, hasta el {date} inclusive.",
    "Source: {source}, until {date}.": "Fuente: {source}, hasta el {date}.",
    "The road ahead": "La calle más adelante",
    "{road} marked closed. Detour posted.": "Cierre en {road}. Desvío señalizado.",
    " This feed was last read more than 20 minutes ago.": (
        " Esta fuente se leyó por última vez hace más de 20 minutos."
    ),
    " This source was last read more than {span} ago.": (
        " Esta fuente se leyó por última vez hace más de {span}."
    ),
    "{n} hours": "{n} horas",
    "{n} minutes": "{n} minutos",
    " You chose to route through it.": " Usted eligió pasar por ella.",
    " No end time is given, so it may still apply on your ride day.": (
        " No tiene hora de fin, así que podría seguir vigente el día de su recorrido."
    ),
    "Work zones could not be checked for this route: {names} not available.": (
        "No se pudieron revisar las zonas de obras de esta ruta: {names} no disponible."
    ),
    "Check before you go: {title} ({source}).": "Revise antes de salir: {title} ({source}).",
    "Work zones are the transportation agencies' own data, read every few minutes. They may be"
    " out of date or wrong, and are not a guarantee the way is open or closed.": (
        "Las zonas de obras son datos de las propias agencias de transporte, leídos cada pocos"
        " minutos. Pueden estar desactualizados o ser incorrectos, y no garantizan que el camino"
        " esté abierto o cerrado."
    ),
}

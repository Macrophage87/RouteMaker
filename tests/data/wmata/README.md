Saved WMATA API answers, shaped as WMATA's developer API documents them
(<https://developer.wmata.com/>): `Rail.svc/json/jStations`,
`StationPrediction.svc/json/GetPrediction/All`, `Incidents.svc/json/Incidents` and
`Incidents.svc/json/ElevatorIncidents`. The stations and their points are real; the trains,
incidents and outages are invented. Read by tests/test_wmata_live.py.

From v0.9.0 (tests/test_wmata_bus.py): `Bus.svc/json/jStops` (`bus-stops.json`),
`NextBusService.svc/json/jPredictions` (`bus-predictions.json`), `Bus.svc/json/jBusPositions`
(`bus-positions.json`), `TrainPositions/TrainPositions` (`train-positions.json`) and
`TrainPositions/StandardRoutes` (`standard-routes.json`). All invented: the stop IDs, buses,
trains and circuits are made up, laid around the fixture timetable's stops and the stations above.

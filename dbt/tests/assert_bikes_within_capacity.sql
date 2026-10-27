-- Un relevé ne doit pas annoncer plus de vélos + bornettes libres que la capacité de la station.
-- Avertissement seulement : le flux réel présente parfois de légers dépassements (capacité mise à jour en retard).
{{ config(severity='warn') }}
select s.station_id, s.polled_at, s.observed_capacity, d.capacity
from {{ ref('stg_velib__station_status') }} as s
inner join {{ ref('dim_station') }} as d on d.station_id = s.station_id
where s.observed_capacity > d.capacity + 2

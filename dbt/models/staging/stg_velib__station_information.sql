-- Dernière version connue de chaque station.
select
    station_id,
    argMax(station_code, updated_at) as station_code,
    argMax(name, updated_at)         as station_name,
    argMax(lat, updated_at)          as lat,
    argMax(lon, updated_at)          as lon,
    argMax(capacity, updated_at)     as capacity,
    max(updated_at)                  as info_updated_at
from {{ source('velib', 'station_information') }}
group by station_id

# Geolocation API (used in the live call task)
`GET https://countries.dev/ip/{ip}` — returns the country for an IP. Example:
```
curl https://countries.dev/ip/8.8.8.8
```
Response (trimmed):
```json
{ "ip": "8.8.8.8", "countryCode": "US", "country": { "name": "United States of America", "region": "Americas" } }
```
In the live task you will treat a provided IP as the "caller IP", fetch its country, and compare it to the
business's `registration_country` / address country to produce a `location_validation` (match | mismatch),
governed by a new Company-Brain rule we hand you on the call.

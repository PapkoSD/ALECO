[out:json][timeout:300];
area["ISO3166-1"="SK"][admin_level=2]->.sk;
(
 // shops selling food made nearby
 nwr["shop"~"^(bakery|farm|organic|health_food|greengrocer|butcher|cheese|dairy|deli|honey|wine)$"](area.sk);
 nwr["organic"~"^(yes|only)$"](area.sk);
 // milk, egg, cheese, meat and potato vending machines
 nwr["vending"~"milk|egg|cheese|dairy|meat|potato|honey|bread|fruit|vegetable"](area.sk);
 nwr["amenity"="marketplace"](area.sk);
 // producers: wineries, beekeepers, cheese makers, mills, farms
 nwr["craft"~"^(winery|beekeeper|cheese|cheesemaker|cheese_maker|bakery|oil_mill|mill|cider|distillery)$"](area.sk);
 nwr["produce"](area.sk);
 nwr["place"="farm"]["name"](area.sk);
 // salaše (sheep farms with cheese) and named farms that are mapped as restaurants or attractions
 nwr["name"~"^[Ss]ala[šs]"]["amenity"](area.sk);
 nwr["name"~"^[Ss]ala[šs]"]["tourism"](area.sk);
 nwr["name"~"^[Ss]ala[šs]"]["shop"](area.sk);
 nwr["name"~"[Ff]arma|[Rr]anč"]["tourism"](area.sk);
 nwr["name"~"[Ff]arma|[Rr]anč"]["amenity"](area.sk);
 nwr["name"~"[Ff]arma|[Rr]anč"]["shop"](area.sk);
);
out tags center;

"""
Script to build and export the Indian places dataset as JSON.
Run: python scripts/build_data.py
"""
import json, os, sys

STATES_CITIES = {
    "Andhra Pradesh": ["Visakhapatnam","Vijayawada","Guntur","Nellore","Kurnool","Rajahmundry","Kakinada","Tirupati","Anantapur","Kadapa","Eluru","Ongole","Nandyal","Machilipatnam","Adoni","Tenali","Chittoor","Hindupur","Bhimavaram","Madanapalle","Guntakal","Dharmavaram","Gudivada","Narasaraopet","Tadipatri","Mangalagiri","Chilakaluripet","Tadepalligudem","Markapur","Kavali","Amaravati","Bapatla","Narasapuram","Palacole","Repalle"],
    "Arunachal Pradesh": ["Itanagar","Naharlagun","Pasighat","Namsai","Bomdila","Ziro","Along","Tezu","Aalo","Khonsa","Changlang","Daporijo","Seppa","Tawang","Roing","Anini","Mechuka","Yingkiong","Deomali","Longding"],
    "Assam": ["Guwahati","Silchar","Dibrugarh","Jorhat","Nagaon","Tinsukia","Tezpur","Bongaigaon","Dhubri","Diphu","Sivasagar","Goalpara","Karimganj","Lakhimpur","Golaghat","Barpeta","Nalbari","Hailakandi","Kokrajhar","Morigaon","Sonitpur","Kamrup","Udalguri","Hojai","Haflong","Lumding","Mangaldoi","Sibsagar","Dhemaji","Majuli","Biswanath Chariali","Charaideo","Bajali","Tamulpur","Cachar"],
    "Bihar": ["Patna","Gaya","Bhagalpur","Muzaffarpur","Purnia","Darbhanga","Bihar Sharif","Arrah","Begusarai","Katihar","Munger","Chhapra","Saharsa","Sasaram","Motihari","Supaul","Hajipur","Dehri","Siwan","Madhubani","Bettiah","Sitamarhi","Ara","Nawada","Kishanganj","Jamalpur","Buxar","Jehanabad","Aurangabad","Samastipur","Rohtas","Jamui","Lakhisarai","Sheikhpura","Arwal"],
    "Chhattisgarh": ["Raipur","Bhilai","Bilaspur","Korba","Durg","Rajnandgaon","Jagdalpur","Raigarh","Ambikapur","Dhamtari","Chirmiri","Mahasamund","Kanker","Tilda Newra","Baloda Bazar","Kondagaon","Kawardha","Bhatapara","Dongargarh","Bijapur","Narayanpur","Balrampur","Sukma","Gariaband","Mungeli"],
    "Goa": ["Panaji","Margao","Vasco da Gama","Mapusa","Ponda","Bicholim","Curchorem","Sanquelim","Cuncolim","Quepem","Canacona","Mormugao","Calangute","Anjuna","Baga","Colva","Benaulim","Candolim","Dona Paula","Old Goa"],
    "Gujarat": ["Ahmedabad","Surat","Vadodara","Rajkot","Bhavnagar","Jamnagar","Junagadh","Gandhinagar","Anand","Navsari","Morbi","Nadiad","Surendranagar","Bharuch","Mehsana","Bhuj","Porbandar","Palanpur","Godhra","Amreli","Botad","Dahod","Khambhat","Gondal","Jetpur","Veraval","Wankaner","Valsad","Vapi","Kapadvanj","Patan","Dahej","Hazira","Mundra","Okha","Dwarka","Somnath","Gir","Saputara","Statue of Unity"],
    "Haryana": ["Faridabad","Gurgaon","Gurugram","Panipat","Ambala","Yamunanagar","Rohtak","Hisar","Karnal","Sonipat","Panchkula","Bhiwani","Sirsa","Bahadurgarh","Jind","Thanesar","Kaithal","Palwal","Rewari","Hansi","Narnaul","Fatehabad","Gohana","Tohana","Mahendragarh","Jhajjar","Mewat","Charkhi Dadri","Pehowa","Kurukshetra"],
    "Himachal Pradesh": ["Shimla","Dharamshala","Solan","Mandi","Palampur","Kullu","Baddi","Nahan","Hamirpur","Chamba","Una","Bilaspur","Kangra","Sundarnagar","Manali","Dalhousie","Kasauli","Rampur","Rohroo","Arki","Kinnaur","Lahaul","Spiti","Keylong","Kaza"],
    "Jharkhand": ["Ranchi","Jamshedpur","Dhanbad","Bokaro","Hazaribagh","Deoghar","Phusro","Giridih","Ramgarh","Medininagar","Chirkunda","Chaibasa","Dumka","Gumla","Lohardaga","Chatra","Godda","Pakur","Jamtara","Sahebganj","Simdega","Khunti","Seraikela","Koderma","Latehar","Garhwa","Palamu"],
    "Karnataka": ["Bangalore","Bengaluru","Mysore","Hubli","Mangalore","Belgaum","Gulbarga","Davanagere","Bellary","Bijapur","Shimoga","Tumkur","Raichur","Bidar","Hospet","Hassan","Gadag","Udupi","Bhadravathi","Chitradurga","Kolar","Mandya","Chikkamagaluru","Gangavati","Bagalkot","Ranibennur","Haveri","Gokak","Yadgir","Sindhanur","Robertsonpet","Vijayapura","Shivamogga","Dharwad","Belagavi"],
    "Kerala": ["Thiruvananthapuram","Kochi","Kozhikode","Thrissur","Kollam","Alappuzha","Palakkad","Malappuram","Kannur","Kasaragod","Kottayam","Idukki","Ernakulam","Pathanamthitta","Wayanad","Munnar","Varkala","Guruvayur","Changanacherry","Thalassery","Tirur","Manjeri","Vatakara","Ponnani","Irinjalakuda","Chalakudy","Perinthalmanna","Punalur","Nedumangad","Attingal"],
    "Madhya Pradesh": ["Bhopal","Indore","Gwalior","Jabalpur","Ujjain","Sagar","Dewas","Satna","Ratlam","Rewa","Murwara","Singrauli","Burhanpur","Khandwa","Bhind","Chhindwara","Guna","Shivpuri","Vidisha","Chhatarpur","Damoh","Mandsaur","Khargone","Neemuch","Pithampur","Hoshangabad","Itarsi","Sehore","Betul","Mandla","Dhar","Shajapur","Agar Malwa","Alirajpur","Anuppur"],
    "Maharashtra": ["Mumbai","Pune","Nagpur","Thane","Nashik","Aurangabad","Solapur","Kolhapur","Amravati","Navi Mumbai","Sangli","Malegaon","Jalgaon","Akola","Latur","Dhule","Ahmednagar","Chandrapur","Parbhani","Nanded","Ichalkaranji","Jalna","Ambarnath","Bhiwandi","Panvel","Yavatmal","Osmanabad","Satara","Ratnagiri","Wardha","Gondia","Beed","Buldhana","Hingoli","Washim"],
    "Manipur": ["Imphal","Thoubal","Bishnupur","Churachandpur","Kakching","Senapati","Ukhrul","Chandel","Tamenglong","Jiribam","Kangpokpi","Pherzawl","Kamjong","Tengnoupal","Noney","Moreh","Moirang","Lilong","Nambol","Wangoi"],
    "Meghalaya": ["Shillong","Tura","Jowai","Nongstoin","Baghmara","Williamnagar","Resubelpara","Nongpoh","Mairang","Cherrapunji","Mawkyrwat","Ampati","Khliehriat","Mawsynram","Dawki","Sohra","Byrnihat","Mawlai","Nongthymmai","Pynthorumkhrah"],
    "Mizoram": ["Aizawl","Lunglei","Champhai","Serchhip","Kolasib","Lawngtlai","Mamit","Saitual","Khawzawl","Hnahthial","Saiha","Tlabung","Zawlnuam","Biate","North Vanlaiphai","Thenzawl","Darlawn","Khawhai","Reiek","Phullen"],
    "Nagaland": ["Kohima","Dimapur","Mokokchung","Tuensang","Wokha","Zunheboto","Phek","Mon","Kiphire","Longleng","Peren","Noklak","Tseminyu","Pfutsero","Chumukedima","Tuli","Aghunato","Changtongya","Mangkolemba","Bhandari"],
    "Odisha": ["Bhubaneswar","Cuttack","Rourkela","Brahmapur","Sambalpur","Puri","Balasore","Bhadrak","Baripada","Jharsuguda","Bargarh","Paradip","Bhawanipatna","Dhenkanal","Kendujhar","Sundargarh","Phulbani","Rayagada","Bolangir","Koraput","Nabarangapur","Kalahandi","Jeypore","Khordha","Jagatsinghpur","Kendrapara","Jajpur","Nayagarh","Subarnapur","Nuapada"],
    "Punjab": ["Ludhiana","Amritsar","Jalandhar","Patiala","Bathinda","Pathankot","Hoshiarpur","Moga","Firozpur","Fatehgarh Sahib","Muktsar","Sangrur","Faridkot","Kapurthala","Barnala","Ropar","Mansa","Gurdaspur","Nawanshahr","Tarn Taran","Fazilka","Sri Muktsar Sahib","Mohali","Rajpura","Khanna","Phagwara","Abohar","Malerkotla","Zirakpur","Morinda"],
    "Rajasthan": ["Jaipur","Jodhpur","Kota","Bikaner","Ajmer","Udaipur","Bhilwara","Alwar","Bharatpur","Sikar","Pali","Sri Ganganagar","Jhalwar","Tonk","Barmer","Kishangarh","Nagaur","Hanumangarh","Sawai Madhopur","Dhaulpur","Dausa","Baran","Sirohi","Jaisalmer","Banswara","Bundi","Pratapgarh","Jhunjhunu","Karauli","Churu","Dungarpur","Rajsamand","Bhilwara","Dholpur","Ganganagar"],
    "Sikkim": ["Gangtok","Namchi","Jorethang","Mangan","Gyalshing","Rangpo","Singtam","Rongli","Soreng","Pakyong","Yuksom","Pelling","Ravangla","Lachung","Lachen","Nathula","Tsomgo","Rumtek","Tashiding","Dentam"],
    "Tamil Nadu": ["Chennai","Coimbatore","Madurai","Tiruchirappalli","Salem","Tirunelveli","Tiruppur","Vellore","Erode","Thoothukkudi","Dindigul","Thanjavur","Kanchipuram","Cuddalore","Nagercoil","Kumbakonam","Sivakasi","Karur","Udhagamandalam","Hosur","Namakkal","Pudukkottai","Ambattur","Avadi","Tiruvottiyur","Rajapalayam","Virudhunagar","Krishnagiri","Dharmapuri","Nagapattinam","Tiruvannamalai","Vellore","Ranipet","Kallakurichi","Tenkasi"],
    "Telangana": ["Hyderabad","Warangal","Nizamabad","Karimnagar","Khammam","Ramagundam","Mahabubnagar","Nalgonda","Adilabad","Suryapet","Miryalaguda","Jagtial","Mancherial","Nirmal","Kothagudem","Bhongir","Vikarabad","Wanaparthy","Gadwal","Sangareddy","Siddipet","Kamareddy","Rajanna Sircilla","Nagarkurnool","Jangaon","Medak","Yadadri Bhuvanagiri","Mulugu","Narayanpet","Bhadradri Kothagudem"],
    "Tripura": ["Agartala","Dharmanagar","Udaipur","Kailasahar","Belonia","Khowai","Ambassa","Pratapgarh","Ranir Bazar","Sabroom","Kumarghat","Teliamura","Sonamura","Bishalgarh","Amarpur","Melaghar","Kamalpur","Santirbazar","Matarbari","Jogendranagar"],
    "Uttar Pradesh": ["Lucknow","Kanpur","Agra","Varanasi","Prayagraj","Ghaziabad","Noida","Meerut","Bareilly","Aligarh","Moradabad","Saharanpur","Gorakhpur","Faizabad","Jhansi","Mathura","Firozabad","Muzaffarnagar","Rampur","Shahjahanpur","Hapur","Loni","Hathras","Sambhal","Bulandshahr","Amroha","Bahraich","Fatehpur","Sitapur","Etawah","Mainpuri","Etah","Hardoi","Lakhimpur Kheri","Unnao","Rae Bareli","Banda","Chitrakoot","Hamirpur UP","Jalaun"],
    "Uttarakhand": ["Dehradun","Haridwar","Roorkee","Haldwani","Rudrapur","Kashipur","Rishikesh","Kotdwar","Ramnagar","Pithoragarh","Almora","Nainital","Mussoorie","Lansdowne","Champawat","Bageshwar","Chamoli","Rudraprayag","Tehri","Uttarkashi","Pauri","Srinagar Uttarakhand","Gopeshwar"],
    "West Bengal": ["Kolkata","Howrah","Durgapur","Asansol","Siliguri","Bardhaman","Malda","Baharampur","Habra","Kharagpur","Shantipur","Dankuni","Dhulian","Ranaghat","Haldia","Raiganj","Krishnanagar","Nabadwip","Medinipur","Jalpaiguri","Balurghat","Bankura","Purulia","Cooch Behar","Darjeeling","Alipurduar","Bongaon","Basirhat","Uluberia","Serampore","Hooghly","Nadia","Murshidabad","Birbhum","South 24 Parganas","North 24 Parganas"],
    "Delhi": ["New Delhi","Old Delhi","Dwarka","Rohini","Janakpuri","Pitampura","Shahdara","Saket","Connaught Place","Karol Bagh","Lajpat Nagar","Greater Kailash","Vasant Kunj","Narela","Bijwasan","Mehrauli","Mayur Vihar","Vivek Vihar","Preet Vihar","Tilak Nagar","Najafgarh","Uttam Nagar","Paschim Vihar","Shalimar Bagh","Model Town"],
    "Jammu and Kashmir": ["Srinagar","Jammu","Baramulla","Anantnag","Sopore","Kathua","Udhampur","Rajouri","Punch","Bandipore","Ganderbal","Kupwara","Shopian","Kulgam","Pulwama","Budgam","Reasi","Samba","Doda","Kishtwar","Ramban","Pahalgam","Gulmarg","Sonmarg","Patnitop","Akhnoor","Vijaypur"],
    "Ladakh": ["Leh","Kargil","Diskit","Padum","Nubra","Zanskar","Drass","Sankoo","Khalsi","Nyoma","Hanle","Turtuk","Chushul","Tangtse","Durbuk","Sumur","Hundar"],
    "Chandigarh": ["Chandigarh","Manimajra","Burail","Maloya","Dhanas","Bapu Dham","Ram Darbar"],
    "Puducherry": ["Puducherry","Pondicherry","Karaikal","Mahe","Yanam","Ozhukarai","Ariyankuppam","Villianur","Oulgaret"],
    "Andaman and Nicobar Islands": ["Port Blair","Diglipur","Rangat","Mayabunder","Car Nicobar","Nancowry","Campbell Bay","Havelock Island","Neil Island","Baratang","Long Island"],
    "Dadra and Nagar Haveli and Daman and Diu": ["Daman","Diu","Silvassa","Naroli","Amli","Khadoli","Masat","Dadra","Nagar Haveli","Rakholi"],
    "Lakshadweep": ["Kavaratti","Agatti","Amini","Androth","Chetlat","Kadmat","Kalpeni","Kiltan","Minicoy"],
}

ROADS = [
    "MG Road","Mahatma Gandhi Road","Nehru Road","Gandhi Road","Ring Road",
    "Outer Ring Road","Inner Ring Road","Bypass Road","National Highway",
    "NH 44","NH 48","NH 8","NH 1","NH 2","NH 3","NH 4","NH 5","NH 6",
    "Mall Road","Station Road","Market Road","Main Road","High Street",
    "Brigade Road","Commercial Street","Church Street","Museum Road",
    "Anna Salai","Mount Road","EVR Periyar Salai","Poonamallee High Road",
    "Park Street","Chowringhee Road","AJC Bose Road","Lenin Sarani",
    "Link Road","Service Road","Old Trunk Road","New Trunk Road",
    "Canal Road","River Road","Lake Road","Hill Road","Forest Road",
    "Rajiv Gandhi Road","Rajiv Gandhi Highway","Indira Gandhi Road",
    "Ambedkar Road","Sardar Patel Road","Subhash Chandra Bose Road",
    "Tilak Road","Shivaji Road","Netaji Road","Bose Road",
    "Residency Road","Palace Road","Fort Road","Civil Lines Road",
    "Cantonment Road","Airport Road","Port Road","Harbour Road",
    "Linking Road","Western Express Highway","Eastern Express Highway",
    "Lal Bahadur Shastri Road","Jawaharlal Nehru Road","Rajendra Prasad Road",
    "Sardar Vallabhbhai Patel Marg","Dr Ambedkar Marg","Aurobindo Marg",
    "Lodhi Road","Mathura Road","GT Road","Grand Trunk Road",
    "Netaji Subhash Marg","Baba Kharak Singh Marg","Kasturba Gandhi Marg",
    "SH 1","SH 2","SH 3","SH 4","SH 5","State Highway 1","State Highway 2",
    "Expressway","Yamuna Expressway","Agra Expressway","Pune Mumbai Expressway",
    "Dwarka Expressway","Delhi Meerut Expressway","Eastern Peripheral Expressway",
    "Western Peripheral Expressway","Ahmedabad Vadodara Expressway",
    "Chennai Bangalore Highway","Bengaluru Mysore Highway",
]

AREAS = [
    "Civil Lines","Cantonment","Old City","New City","City Centre",
    "Industrial Area","Industrial Estate","MIDC","SEZ","IT Park",
    "Technopark","Electronic City","Software Technology Park",
    "Adarsh Nagar","Pratap Nagar","Shastri Nagar","Gandhi Nagar",
    "Nehru Nagar","Indira Nagar","Rajendra Nagar","Ambedkar Nagar",
    "Subhash Nagar","Sarojini Nagar","Tilak Nagar","Karol Bagh",
    "Connaught Place","Chandni Chowk","Lajpat Nagar","Greater Kailash",
    "Defence Colony","Vasant Vihar","Janakpuri","Rohini","Pitampura",
    "Malviya Nagar","Hauz Khas","Green Park","Safdarjung Enclave",
    "Koramangala","Jayanagar","Rajajinagar","Vijayanagar",
    "Whitefield","Marathahalli","HSR Layout","BTM Layout",
    "Andheri","Bandra","Juhu","Kurla","Dadar","Worli",
    "Chembur","Mulund","Thane","Kalyan","Vasai","Virar",
    "Banjara Hills","Jubilee Hills","Hitech City","Gachibowli",
    "Madhapur","Kukatpally","Secunderabad","Uppal","Dilsukhnagar",
    "T Nagar","Adyar","Velachery","Tambaram","Perungalathur",
    "Chromepet","Pallikaranai","Sholinganallur","Perungudi",
    "Salt Lake","New Town","Rajarhat","Dum Dum","Behala",
    "Barasat","Barrackpore","Khardah","Titagarh","Naihati",
    "Dwarka","Rohini","Noida Extension","Greater Noida","Faridabad",
    "Gurgaon Sector 14","Gurgaon Sector 29","Gurgaon Sector 56",
    "Powai","Andheri East","Andheri West","Goregaon","Malad",
    "Borivali","Kandivali","Dahisar","Mira Road","Bhayander",
    "Pimpri","Chinchwad","Hadapsar","Kothrud","Aundh","Baner",
    "Hinjewadi","Wakad","Pimple Saudagar","Shivajinagar Pune",
    "Koregaon Park","Kalyani Nagar","Viman Nagar","Kharadi",
    "Yelahanka","Hebbal","Devanahalli","Domlur","Indiranagar Bangalore",
    "Sadashivanagar","Rajmahal Vilas","Malleswaram","Basavanagudi",
]

LANDMARKS = [
    "India Gate","Red Fort","Qutub Minar","Humayuns Tomb","Lotus Temple",
    "Akshardham Temple","Jama Masjid","Raj Ghat","Parliament House",
    "Rashtrapati Bhavan","Vigyan Bhavan",
    "Gateway of India","Marine Drive","Chhatrapati Shivaji Terminus",
    "Siddhivinayak Temple","Haji Ali Dargah","Elephanta Caves","Juhu Beach",
    "Meenakshi Amman Temple","Brihadeeswarar Temple","Shore Temple","Marina Beach",
    "Golconda Fort","Charminar","Salar Jung Museum","Hussain Sagar Lake",
    "Mysore Palace","Vidhana Soudha","Cubbon Park","Lal Bagh",
    "Victoria Memorial","Howrah Bridge","Dakshineswar Kali Temple","Belur Math",
    "Taj Mahal","Agra Fort","Fatehpur Sikri","Sikandra",
    "Hawa Mahal","Amber Fort","City Palace Jaipur","Jantar Mantar",
    "Sun Temple Konark","Jagannath Temple Puri","Lingaraj Temple Bhubaneswar",
    "Vaishno Devi Temple","Amarnath Cave","Dal Lake","Shalimar Bagh",
    "Golden Temple","Jallianwala Bagh","Wagah Border","Anandpur Sahib",
    "Kedarnath Temple","Badrinath Temple","Rishikesh","Haridwar Ghat",
    "Ellora Caves","Ajanta Caves","Shirdi Sai Baba Temple","Trimbakeshwar Temple",
    "Rameswaram Temple","Kanyakumari","Somnath Temple","Dwarka Temple",
    "Tirupati Balaji Temple","Shirdi","Nashik Kumbh","Ujjain Mahakaleshwar",
    "Varanasi Ghats","Bodh Gaya","Nalanda","Rajgir",
    "Kaziranga National Park","Ranthambore National Park","Jim Corbett Park",
    "Sundarbans","Gir National Park","Kanha National Park","Bandhavgarh",
    "Backwaters Kerala","Munnar Tea Gardens","Coorg Coffee Estates",
    "Dudhsagar Falls","Athirapally Falls","Jog Falls",
]

VILLAGE_SUFFIXES = ["pur","gaon","wadi","palli","puram","kalan","khurd","nagar",
                     "abad","ganj","hat","bazar","tola","dih","para","peta","guda",
                     "gudem","pet","patna","pura","garh","kot","wala","wali","tanda",
                     "khera","mau","dehi","chaur","danda","kundi","guda","wada"]

VILLAGE_PREFIXES = ["Ram","Shyam","Krishna","Lakshmi","Shiva","Durga","Kali","Vishnu",
                     "Brahma","Indra","Arjun","Bharat","Hari","Gopal","Mohan","Sohan",
                     "Rohan","Kishan","Balram","Suresh","Dinesh","Mahesh","Rajesh",
                     "Naresh","Ramesh","Umesh","Girish","Harish","Manish","Ganesh",
                     "Prakash","Aakash","Vikash","Deepak","Vivek","Santosh","Rakesh",
                     "Mukesh","Devi","Mata","Nath","Prasad","Lal","Das","Chandra",
                     "Bai","Soni","Lodi","Rawat","Gujar","Jat","Yadav","Teli",
                     "Ahir","Kurmi","Lodha","Patel","Shah","Mehta","Sharma","Verma",
                     "Singh","Chauhan","Rajput","Thakur","Pandit","Mishra","Tiwari"]

def build_villages():
    return [f"{p}{s}" for p in VILLAGE_PREFIXES for s in VILLAGE_SUFFIXES]

def build_all_names():
    names = {}
    names["villages"] = build_villages()
    all_cities = []
    for state, cities in STATES_CITIES.items():
        all_cities.extend(cities)
    names["cities"] = all_cities
    names["states"] = list(STATES_CITIES.keys())
    names["roads"] = ROADS
    names["areas"] = AREAS
    names["landmarks"] = LANDMARKS
    names["union_territories"] = [
        "Delhi","Chandigarh","Puducherry","Lakshadweep",
        "Dadra and Nagar Haveli and Daman and Diu",
        "Andaman and Nicobar Islands","Jammu and Kashmir","Ladakh"
    ]
    names["districts"] = list({c for cities in STATES_CITIES.values() for c in cities[:8]})
    return names

if __name__ == "__main__":
    data = build_all_names()
    total = sum(len(v) for v in data.values())
    print(f"Total entries: {total}")
    out = os.path.join(os.path.dirname(__file__), "..", "indic_places", "data", "places.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Written to {out}")

"""Test scenarios for legal qualification validation."""

SCENARIOS = [
    # ── Trestné činy (TC) ──
    {
        "id": "tc_simple_theft",
        "popis_skutku": (
            "Pachatel odcizil z obchodu zboží v hodnotě 5 000 Kč, "
            "které schoval do batohu a prošel bez zaplacení u pokladny."
        ),
        "typ": "TC",
        "expected_paragraphs": ["205"],
        "expected_notes": ["škoda nepatrná"],
    },
    {
        "id": "tc_qualified_theft",
        "popis_skutku": (
            "Organizovaná skupina opakovaně kradla elektroniku z obchodních "
            "center po celé Praze. Celková škoda dosáhla 200 000 Kč."
        ),
        "typ": "TC",
        "expected_paragraphs": ["205"],
        "expected_notes": ["organizovaná skupina", "škoda značná"],
    },
    {
        "id": "tc_burglary_concurrent",
        "popis_skutku": (
            "Pachatel v noci vnikl do bytu poškozeného tím, že vypáčil zámek "
            "vstupních dveří, a odcizil šperky v hodnotě 80 000 Kč."
        ),
        "typ": "TC",
        "expected_paragraphs": ["205", "178"],
        "expected_notes": ["souběh", "porušování domovní svobody"],
    },
    {
        "id": "tc_attempted_theft",
        "popis_skutku": (
            "Pachatel se pokusil vniknout do bankomatu pomocí páčidla, "
            "ale byl vyrušen projíždějící hlídkou Policie ČR a z místa utekl."
        ),
        "typ": "TC",
        "expected_paragraphs": ["205"],
        "expected_notes": ["pokus", "§ 21"],
    },
    {
        "id": "tc_assault",
        "popis_skutku": (
            "Pachatel v restauraci po slovní rozepři udeřil poškozeného "
            "pěstí do obličeje, čímž mu způsobil zlomeninu nosu s dobou "
            "léčení 3 týdny."
        ),
        "typ": "TC",
        "expected_paragraphs": ["146"],
        "expected_notes": ["úmyslný"],
    },
    {
        "id": "tc_fraud",
        "popis_skutku": (
            "Pachatel na internetovém bazaru inzeroval prodej notebooku za "
            "15 000 Kč. Po obdržení platby zboží neodeslal a přestal "
            "komunikovat. Poškozeno bylo 8 kupujících, celková škoda 120 000 Kč."
        ),
        "typ": "TC",
        "expected_paragraphs": ["209"],
        "expected_notes": ["škoda větší"],
    },
    {
        "id": "tc_drug_possession_large",
        "popis_skutku": (
            "Při domovní prohlídce bylo u podezřelého nalezeno 50 gramů "
            "metamfetaminu (pervitinu) rozděleného do sáčků."
        ),
        "typ": "TC",
        "expected_paragraphs": ["283"],
        "expected_notes": ["větší než malé množství"],
    },
    # ── Trestné činy s okolnostmi vylučujícími protiprávnost ──
    {
        "id": "tc_self_defense_clear",
        "popis_skutku": ("Muž na mě zaútočil nožem, bránil jsem se a zlomil mu ruku."),
        "typ": "TC",
        "expected_paragraphs": ["146"],
        "expected_notes": ["nutná obrana", "§ 29"],
    },
    {
        "id": "tc_extreme_necessity",
        "popis_skutku": (
            "Při požáru jsem vyrazil dveře souseda, abych zachránil dítě "
            "uvězněné v hořícím bytě. Dveře jsem tím zničil."
        ),
        "typ": "TC",
        "expected_paragraphs": ["228"],
        "expected_notes": ["krajní nouze", "§ 28"],
    },
    {
        "id": "tc_exceeded_defense",
        "popis_skutku": ("Muž na mě zaútočil, já ho pronásledoval 500 metrů a zbil ho."),
        "typ": "TC",
        "expected_paragraphs": ["146"],
        "expected_notes": ["překročení mezí", "exces"],
    },
    {
        "id": "tc_consent_sport",
        "popis_skutku": (
            "Během amatérského boxerského zápasu jeden z účastníků zasadil "
            "soupeři ránu, která mu způsobila zlomeninu čelisti."
        ),
        "typ": "TC",
        "expected_paragraphs": ["146"],
        "expected_notes": ["svolení poškozeného", "§ 30"],
    },
    {
        "id": "tc_no_defense_negative",
        "popis_skutku": (
            "Pachatel přepadl v noci ženu na ulici a odcizil jí kabelku "
            "s doklady a hotovostí 3 000 Kč."
        ),
        "typ": "TC",
        "expected_paragraphs": ["173"],
        "expected_notes": ["loupež"],
    },
    {
        "id": "tc_partial_defense_concurrent",
        "popis_skutku": (
            "Pachatel se bránil útoku nožem a přitom napadl útočníka (zlomil mu "
            "ruku) a zároveň poškodil cizí automobil, o který útočníka srazil."
        ),
        "typ": "TC",
        "expected_paragraphs": ["146", "228"],
        "expected_notes": ["nutná obrana", "§ 29"],
    },
    {
        "id": "tc_home_invasion_defense",
        "popis_skutku": (
            "Dne 14. února 2026 kolem 22:30 vnikli tři maskovaní pachatelé "
            "do bytu Radka M. (44 let) v ulici Mánesova 7, Praha 2, a to po "
            "vypáčení vstupních dveří. V bytě se nacházeli Radek M., jeho "
            "manželka Jana M. (41 let) a jejich dvě děti (9 a 11 let). "
            "Radek M. byl v ložnici, kde zaslechl hlasitý třesk vypáčených "
            "dveří a křik. Okamžitě odemkl bezpečnostní schránku u postele "
            "a vzal legálně drženou pistoli CZ P-10C, ráže 9 mm Luger, ke "
            "které je oprávněn na základě zbrojního průkazu skupiny B. Do "
            "chodby vstoupil v momentě, kdy na něj první pachatel mířil "
            "krátkou střelnou zbraní a vykřikoval výhružky. Radek M. vystřelil "
            "třikrát; první pachatel byl zasažen do hrudníku a na místě zemřel. "
            "Zbývající dva pachatelé zahájili palbu – celkem padlo 5 výstřelů "
            "z jejich strany, Radek M. byl zasažen do levého ramene. Za střelby "
            "ustupoval Radek M. zpět do chodby a vypálil dalších čtyři "
            "výstřely; druhý pachatel byl zasažen do břicha a zemřel na místě, "
            "třetí byl zasažen do stehna, zhroutil se a byl do příjezdu policie "
            "znehybněn. Radek M. byl ošetřen záchrannou službou a "
            "hospitalizován; jeho manželka a děti nebyli fyzicky zraněni. "
            "U pachatelů byly nalezeny nelegálně držené střelné zbraně a pásky "
            "na svazování."
        ),
        "typ": "TC",
        "expected_paragraphs": ["146", "140"],
        "expected_notes": ["nutná obrana", "§ 29"],
    },
    # ── Přestupky (PR) ──
    {
        "id": "pr_speeding",
        "popis_skutku": (
            "Řidič překročil povolenou rychlost o 40 km/h v obci, "
            "což bylo zaznamenáno automatickým radarem."
        ),
        "typ": "PR",
        "expected_paragraphs": ["125c"],
        "expected_notes": ["dopravní přestupek"],
    },
    {
        "id": "pr_drug_personal",
        "popis_skutku": "Osoba držela 2 gramy marihuany pro vlastní potřebu.",
        "typ": "PR",
        "expected_paragraphs": [],
        "expected_notes": ["osobní potřeba"],
    },
    {
        "id": "pr_defense_sidewalk",
        "popis_skutku": (
            "Řidič vjel na chodník, aby se vyhnul čelní srážce s protijedoucím "
            "vozidlem, které vyjelo do protisměru. Při tom srazil dopravní "
            "značku a poškodil sloup veřejného osvětlení."
        ),
        "typ": "PR",
        "expected_paragraphs": [],
        "expected_notes": ["krajní nouze", "§ 28"],
    },
    # ── Negative cases ──
    {
        "id": "neg_nonsense",
        "popis_skutku": ("Dnes je hezky a svítí sluníčko, jdu na procházku se psem do parku."),
        "typ": "TC",
        "expected_paragraphs": [],
        "expected_notes": ["nepodařilo se kvalifikovat"],
    },
    {
        "id": "neg_civil_dispute",
        "popis_skutku": (
            "Soused mi dluží 5 000 Kč za opravu plotu, kterou jsem provedl "
            "na základě ústní dohody před třemi měsíci. Odmítá zaplatit."
        ),
        "typ": "TC",
        "expected_paragraphs": [],
        "expected_notes": ["civilní spor"],
    },
    {
        "id": "neg_vague",
        "popis_skutku": "Někdo něco udělal a bylo to špatné, myslím.",
        "typ": "TC",
        "expected_paragraphs": [],
        "expected_notes": ["nedostatečný popis"],
    },
]

"""Reference data shipped with the app. Shops override everything in Shop Settings.

Material prices are reference values only (bar/plate, USD/kg, small-lot distributor pricing, Nov 2026
snapshot). They are NOT live market data; each shop should enter its own supplier prices, and the
app warns when a price is older than the shop's staleness limit.
"""

MATERIALS = [
    # code, name, aliases, family, density g/cm3, machinability (6061 = 1.0), ref $/kg
    ("AL6061", "Aluminum 6061-T6", ["6061", "6061-T6", "6061-T651", "AL 6061", "ALUMINUM 6061", "ALUMINIUM 6061"], "aluminum", 2.70, 1.00, 7.5),
    ("AL6082", "Aluminum 6082-T6", ["6082", "6082-T6", "6082-T651"], "aluminum", 2.70, 1.00, 7.5),
    ("AL7075", "Aluminum 7075-T6/T651", ["7075", "7075-T6", "7075-T651", "7075-T7351", "AL 7075"], "aluminum", 2.81, 0.90, 12.0),
    ("AL2024", "Aluminum 2024-T3/T351", ["2024", "2024-T3", "2024-T351"], "aluminum", 2.78, 0.85, 13.0),
    ("AL5052", "Aluminum 5052-H32", ["5052"], "aluminum", 2.68, 0.85, 7.0),
    ("ST1018", "Steel 1018", ["1018", "C1018", "AISI 1018"], "steel", 7.87, 0.30, 3.0),
    ("ST1045", "Steel 1045", ["1045", "C45", "AISI 1045"], "steel", 7.85, 0.26, 3.2),
    ("ST4140", "Steel 4140 (annealed / pre-hard)", ["4140", "AISI 4140", "4140 PH", "42CRMO4"], "steel", 7.85, 0.20, 4.2),
    ("ST4340", "Steel 4340", ["4340", "AISI 4340"], "steel", 7.85, 0.16, 6.5),
    ("ST12L14", "Steel 12L14", ["12L14"], "steel", 7.87, 0.55, 3.2),
    ("TS_A2", "Tool steel A2", ["A2", "A-2"], "tool_steel", 7.86, 0.14, 11.0),
    ("TS_D2", "Tool steel D2", ["D2", "D-2"], "tool_steel", 7.70, 0.10, 12.0),
    ("SS303", "Stainless 303", ["303", "SS303", "AISI 303"], "stainless", 8.00, 0.22, 8.0),
    ("SS304", "Stainless 304/304L", ["304", "304L", "SS304", "AISI 304"], "stainless", 8.00, 0.16, 7.5),
    ("SS316", "Stainless 316/316L", ["316", "316L", "SS316", "AISI 316"], "stainless", 8.00, 0.14, 9.5),
    ("SS174", "Stainless 17-4 PH", ["17-4", "17-4PH", "17-4 PH", "630"], "stainless", 7.80, 0.12, 14.0),
    ("TI64", "Titanium 6Al-4V", ["TI-6AL-4V", "TI6AL4V", "6AL-4V", "GRADE 5", "TITANIUM"], "titanium", 4.43, 0.08, 45.0),
    ("IN718", "Inconel 718", ["718", "INCONEL", "INCONEL 718"], "nickel", 8.19, 0.04, 70.0),
    ("BR360", "Brass C360", ["C360", "C36000", "BRASS", "360 BRASS"], "copper", 8.50, 1.20, 11.0),
    ("CU110", "Copper C110", ["C110", "C11000", "COPPER"], "copper", 8.89, 0.45, 14.0),
    ("POM", "Acetal (Delrin)", ["DELRIN", "ACETAL", "POM"], "plastic", 1.41, 1.30, 9.0),
    ("PEEK", "PEEK", ["PEEK"], "plastic", 1.32, 0.80, 110.0),
    ("UHMW", "UHMW-PE", ["UHMW"], "plastic", 0.94, 1.30, 8.0),
    ("NYLON", "Nylon 6/6", ["NYLON"], "plastic", 1.14, 1.20, 8.0),
    ("PC", "Polycarbonate", ["POLYCARBONATE", "LEXAN"], "plastic", 1.20, 1.10, 10.0),
]
REFERENCE_DATE = "2026-11-01"
WORST_CASE_MATERIAL = "SS316"  # used when material is unknown (conservative)

DEFAULT_RATES = [
    ("milling", "3-axis milling", 95.0),
    ("milling4", "4-axis milling", 115.0),
    ("milling5", "5-axis milling", 145.0),
    ("turning", "CNC turning", 90.0),
    ("millturn", "Mill-turn", 140.0),
    ("setup", "Setup", 85.0),
    ("programming", "CAM programming", 95.0),
    ("inspection", "Inspection / CMM", 90.0),
    ("deburr", "Deburr / bench", 55.0),
]

DEFAULT_MACHINES = [
    ("VMC 3-axis (40x20x20 in)", "mill3", "milling", [1016, 508, 508], {}),
    ("VMC + 4th axis", "mill4", "milling4", [762, 406, 508], {}),
    ("5-axis trunnion", "mill5", "milling5", [500, 400, 350], {}),
    ("CNC lathe (Ø300 x 500)", "lathe", "turning", [300, 500], {"bar_capacity_mm": 52}),
]

DEFAULT_OUTSIDE = [
    # name, keywords, basis, price, lot charge
    ("Anodize Type II (clear/color)", ["ANODIZE", "ANODISE", "MIL-A-8625 TYPE II", "MIL-PRF-8625 TYPE II"], "per_dm2", 0.60, 125.0),
    ("Hard anodize Type III", ["HARD ANODIZE", "HARDCOAT", "HARD COAT", "TYPE III"], "per_dm2", 1.40, 175.0),
    ("Chem film / Alodine", ["CHEM FILM", "ALODINE", "MIL-DTL-5541", "CHROMATE CONVERSION", "IRIDITE"], "per_dm2", 0.35, 100.0),
    ("Black oxide", ["BLACK OXIDE", "MIL-DTL-13924", "BLACKEN"], "per_kg", 6.0, 90.0),
    ("Passivation", ["PASSIVATE", "PASSIVATION", "ASTM A967", "AMS 2700"], "per_kg", 5.0, 95.0),
    ("Zinc plating", ["ZINC PLAT", "ASTM B633"], "per_kg", 4.0, 90.0),
    ("Electroless nickel", ["ELECTROLESS NICKEL", "AMS 2404", "ASTM B733", "EN PLATE"], "per_dm2", 1.20, 150.0),
    ("Powder coat", ["POWDER COAT"], "per_dm2", 0.90, 150.0),
    ("Heat treat (harden / Q&T)", ["HEAT TREAT", "HRC", "Q&T", "HARDEN", "QUENCH"], "per_kg", 4.5, 150.0),
    ("Stress relieve", ["STRESS RELIEVE", "STRESS RELIEF"], "per_kg", 3.0, 125.0),
    ("Nitriding", ["NITRID"], "per_kg", 7.0, 200.0),
    ("Bead blast", ["BEAD BLAST", "GLASS BEAD"], "per_dm2", 0.30, 60.0),
    ("Material / CoC certification pack", ["MATERIAL CERT", "3.1 CERT", "EN 10204", "CERTIFICATE OF CONFORMITY", "C OF C", "COC"], "per_lot", 0.0, 35.0),
    ("First article inspection report", ["FIRST ARTICLE", "FAI", "AS9102"], "per_lot", 0.0, 350.0),
]

DEFAULT_SHOP_SETTINGS = {
    "margin_pct": 20.0,
    "contingency_pct": 5.0,           # always applied
    "uncertainty_pct_per_item": 3.0,  # extra per low-confidence / unrecognised item ...
    "uncertainty_cap_pct": 25.0,      # ... capped
    "material_scrap_pct": 10.0,       # saw kerf, facing, drops
    "stock_allowance_mm": 3.0,        # per side, milling
    "turning_allowance_mm": 3.0,      # on diameter, per side
    "turning_length_allowance_mm": 6.0,
    "min_material_per_part": 2.0,
    "min_order_charge": 150.0,
    "setup_hours_per_setup": 0.75,
    "first_article_hours": 0.5,
    "programming_base_hours": 0.75,
    "programming_hours_per_feature": 0.03,
    "programming_hours_per_setup": 0.25,
    "handling_min_per_setup": 1.5,
    "deburr_min_base": 1.0,
    "inspection_min_base": 1.0,
    "inspection_min_per_critical": 0.4,
    "price_rounding": 0.05,
    "material_price_stale_days": 90,
    "time_calibration_factor": 1.0,   # tuned from historical actual hours
    "volume_tiers": [                 # discount on machining + setup + programming only
        {"min_qty": 1, "discount_pct": 0.0},
        {"min_qty": 25, "discount_pct": 3.0},
        {"min_qty": 100, "discount_pct": 6.0},
        {"min_qty": 500, "discount_pct": 9.0},
    ],
    # baseline removal rates on a 3-axis VMC in 6061 (cm3/min); scaled by machinability
    "mrr_rough_cm3_min": 60.0,
    "finish_min_per_dm2": 1.2,
}

-- Surreal FA — Knowledge Graph Schema
-- Apply via: uv run python -m src.schema.apply

-- ============================================================
-- NODE TABLES
-- ============================================================

DEFINE TABLE industry SCHEMAFULL;
DEFINE FIELD name            ON TABLE industry TYPE string;
DEFINE FIELD description     ON TABLE industry TYPE option<string>;
DEFINE FIELD sector          ON TABLE industry TYPE option<string>;
DEFINE FIELD market_size_usd ON TABLE industry TYPE option<float>;
DEFINE FIELD source          ON TABLE industry TYPE option<string>;
DEFINE FIELD created_at      ON TABLE industry TYPE datetime VALUE time::now();
DEFINE INDEX idx_industry_name ON TABLE industry COLUMNS name UNIQUE;

DEFINE TABLE company SCHEMAFULL;
DEFINE FIELD name         ON TABLE company TYPE string;
DEFINE FIELD ticker       ON TABLE company TYPE option<string>;
DEFINE FIELD description  ON TABLE company TYPE option<string>;
DEFINE FIELD market_cap   ON TABLE company TYPE option<float>;
DEFINE FIELD revenue      ON TABLE company TYPE option<float>;
DEFINE FIELD employees    ON TABLE company TYPE option<int>;
DEFINE FIELD hq_country   ON TABLE company TYPE option<string>;
DEFINE FIELD hq_city      ON TABLE company TYPE option<string>;
DEFINE FIELD website      ON TABLE company TYPE option<string>;
DEFINE FIELD wikidata_id  ON TABLE company TYPE option<string>;
DEFINE FIELD founded      ON TABLE company TYPE option<string>;
DEFINE FIELD source       ON TABLE company TYPE option<string>;
DEFINE FIELD created_at   ON TABLE company TYPE datetime VALUE time::now();
DEFINE INDEX idx_company_name   ON TABLE company COLUMNS name UNIQUE;
DEFINE INDEX idx_company_ticker ON TABLE company COLUMNS ticker;

DEFINE TABLE technology SCHEMAFULL;
DEFINE FIELD name           ON TABLE technology TYPE string;
DEFINE FIELD description    ON TABLE technology TYPE option<string>;
DEFINE FIELD maturity       ON TABLE technology TYPE option<string>;
DEFINE FIELD adoption_stage ON TABLE technology TYPE option<string>;
DEFINE FIELD source         ON TABLE technology TYPE option<string>;
DEFINE FIELD created_at     ON TABLE technology TYPE datetime VALUE time::now();
DEFINE INDEX idx_tech_name ON TABLE technology COLUMNS name UNIQUE;

DEFINE TABLE commodity SCHEMAFULL;
DEFINE FIELD name          ON TABLE commodity TYPE string;
DEFINE FIELD description   ON TABLE commodity TYPE option<string>;
DEFINE FIELD category      ON TABLE commodity TYPE option<string>;
DEFINE FIELD current_price        ON TABLE commodity TYPE option<float>;
DEFINE FIELD concentration_score  ON TABLE commodity TYPE option<float>;
DEFINE FIELD source               ON TABLE commodity TYPE option<string>;
DEFINE FIELD created_at    ON TABLE commodity TYPE datetime VALUE time::now();
DEFINE INDEX idx_commodity_name ON TABLE commodity COLUMNS name UNIQUE;

DEFINE TABLE policy SCHEMAFULL;
DEFINE FIELD name           ON TABLE policy TYPE string;
DEFINE FIELD description    ON TABLE policy TYPE option<string>;
DEFINE FIELD policy_type    ON TABLE policy TYPE option<string>;
DEFINE FIELD region         ON TABLE policy TYPE option<string>;
DEFINE FIELD status         ON TABLE policy TYPE option<string>;
DEFINE FIELD source         ON TABLE policy TYPE option<string>;
DEFINE FIELD created_at     ON TABLE policy TYPE datetime VALUE time::now();
DEFINE INDEX idx_policy_name ON TABLE policy COLUMNS name UNIQUE;

DEFINE TABLE event SCHEMAFULL;
DEFINE FIELD name          ON TABLE event TYPE string;
DEFINE FIELD description   ON TABLE event TYPE option<string>;
DEFINE FIELD event_type    ON TABLE event TYPE option<string>;
DEFINE FIELD polymarket_id ON TABLE event TYPE option<string>;
DEFINE FIELD probability   ON TABLE event TYPE option<float>;
DEFINE FIELD timeframe     ON TABLE event TYPE option<string>;
DEFINE FIELD source        ON TABLE event TYPE option<string>;
DEFINE FIELD created_at    ON TABLE event TYPE datetime VALUE time::now();
DEFINE INDEX idx_event_name ON TABLE event COLUMNS name;

DEFINE TABLE region SCHEMAFULL;
DEFINE FIELD name         ON TABLE region TYPE string;
DEFINE FIELD country_code ON TABLE region TYPE option<string>;
DEFINE FIELD lat          ON TABLE region TYPE option<float>;
DEFINE FIELD lng          ON TABLE region TYPE option<float>;
DEFINE FIELD source       ON TABLE region TYPE option<string>;
DEFINE FIELD created_at   ON TABLE region TYPE datetime VALUE time::now();
DEFINE INDEX idx_region_name ON TABLE region COLUMNS name UNIQUE;

-- ============================================================
-- EDGE TABLES
-- ============================================================

DEFINE TABLE operates_in TYPE RELATION IN company OUT industry;
DEFINE FIELD market_share ON TABLE operates_in TYPE option<float>;
DEFINE FIELD revenue_pct  ON TABLE operates_in TYPE option<float>;
DEFINE FIELD role         ON TABLE operates_in TYPE option<string>;
DEFINE FIELD confidence   ON TABLE operates_in TYPE option<float>;
DEFINE FIELD source       ON TABLE operates_in TYPE option<string>;

DEFINE TABLE competes_with TYPE RELATION IN company OUT company;
DEFINE FIELD overlap_score ON TABLE competes_with TYPE option<float>;
DEFINE FIELD segments      ON TABLE competes_with TYPE option<array<string>>;
DEFINE FIELD confidence    ON TABLE competes_with TYPE option<float>;
DEFINE FIELD source        ON TABLE competes_with TYPE option<string>;

DEFINE TABLE supplies_to TYPE RELATION IN company OUT company;
DEFINE FIELD products            ON TABLE supplies_to TYPE option<array<string>>;
DEFINE FIELD revenue_dependency  ON TABLE supplies_to TYPE option<float>;
DEFINE FIELD criticality         ON TABLE supplies_to TYPE option<string>;
DEFINE FIELD confidence          ON TABLE supplies_to TYPE option<float>;
DEFINE FIELD source              ON TABLE supplies_to TYPE option<string>;

DEFINE TABLE complement_of TYPE RELATION IN company OUT company;
DEFINE FIELD reason     ON TABLE complement_of TYPE option<string>;
DEFINE FIELD confidence ON TABLE complement_of TYPE option<float>;
DEFINE FIELD source     ON TABLE complement_of TYPE option<string>;

DEFINE TABLE substitute_for TYPE RELATION IN company OUT company;
DEFINE FIELD substitutability ON TABLE substitute_for TYPE option<float>;
DEFINE FIELD switching_cost   ON TABLE substitute_for TYPE option<string>;
DEFINE FIELD confidence       ON TABLE substitute_for TYPE option<float>;
DEFINE FIELD source           ON TABLE substitute_for TYPE option<string>;

DEFINE TABLE subsidiary_of TYPE RELATION IN company OUT company;
DEFINE FIELD ownership_pct ON TABLE subsidiary_of TYPE option<float>;
DEFINE FIELD confidence    ON TABLE subsidiary_of TYPE option<float>;
DEFINE FIELD source        ON TABLE subsidiary_of TYPE option<string>;

DEFINE TABLE uses_technology TYPE RELATION IN company OUT technology;
DEFINE FIELD criticality ON TABLE uses_technology TYPE option<string>;
DEFINE FIELD confidence  ON TABLE uses_technology TYPE option<float>;
DEFINE FIELD source      ON TABLE uses_technology TYPE option<string>;

DEFINE TABLE invested_in TYPE RELATION IN company OUT company;
DEFINE FIELD amount     ON TABLE invested_in TYPE option<float>;
DEFINE FIELD confidence ON TABLE invested_in TYPE option<float>;
DEFINE FIELD source     ON TABLE invested_in TYPE option<string>;

DEFINE TABLE uses_input TYPE RELATION IN company OUT commodity;
DEFINE FIELD cost_sensitivity ON TABLE uses_input TYPE option<float>;
DEFINE FIELD pct_of_costs     ON TABLE uses_input TYPE option<float>;
DEFINE FIELD confidence       ON TABLE uses_input TYPE option<float>;
DEFINE FIELD source           ON TABLE uses_input TYPE option<string>;

DEFINE TABLE demand_driver TYPE RELATION IN event OUT industry;
DEFINE FIELD direction  ON TABLE demand_driver TYPE option<string>;
DEFINE FIELD magnitude  ON TABLE demand_driver TYPE option<string>;
DEFINE FIELD confidence ON TABLE demand_driver TYPE option<float>;
DEFINE FIELD source     ON TABLE demand_driver TYPE option<string>;

DEFINE TABLE affected_by_policy TYPE RELATION IN company OUT policy;
DEFINE FIELD impact_direction ON TABLE affected_by_policy TYPE option<string>;
DEFINE FIELD magnitude        ON TABLE affected_by_policy TYPE option<string>;
DEFINE FIELD confidence       ON TABLE affected_by_policy TYPE option<float>;
DEFINE FIELD source           ON TABLE affected_by_policy TYPE option<string>;

DEFINE TABLE produced_in TYPE RELATION IN commodity OUT region;
DEFINE FIELD pct_of_global_supply ON TABLE produced_in TYPE option<float>;
DEFINE FIELD source               ON TABLE produced_in TYPE option<string>;

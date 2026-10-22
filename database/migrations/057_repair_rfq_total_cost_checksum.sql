-- Apply the freight validation constraint missing from the already-applied 056.
-- The migration runner checks the existing definition and reconciles 056's ledger checksum.
ALTER TABLE supplier_quote_items
    ADD CONSTRAINT chk_quote_item_freight CHECK (
        (freight_amount IS NULL OR freight_amount >= 0)
        AND (freight_tax_rate IS NULL OR freight_tax_rate BETWEEN 0 AND 100)
    );

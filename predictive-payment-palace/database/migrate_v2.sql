-- Optional manual migration (app also upgrades on startup).
USE predictive_payment_palace;

-- Run each ALTER only once; ignore "Duplicate column" errors if already applied.
ALTER TABLE menu_items ADD COLUMN current_prep INT NOT NULL DEFAULT 0;
ALTER TABLE menu_items ADD COLUMN portion_note VARCHAR(150) NULL;
ALTER TABLE menu_items ADD COLUMN price DECIMAL(10,2) NULL;

CREATE TABLE IF NOT EXISTS users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    business_id INT NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(100),
    FOREIGN KEY (business_id) REFERENCES businesses(id)
);

UPDATE menu_items SET current_prep = 12, portion_note = '2 pcs chicken + 2 sides', price = 14.00 WHERE id = 1;
UPDATE menu_items SET current_prep = 8, portion_note = '8 oz', price = 4.50 WHERE id = 2;
UPDATE menu_items SET current_prep = 6, portion_note = '6 oz', price = 4.00 WHERE id = 3;
UPDATE menu_items SET current_prep = 4, portion_note = '6 oz', price = 4.00 WHERE id = 4;
UPDATE menu_items SET current_prep = 10, portion_note = '1 piece', price = 1.50 WHERE id = 5;

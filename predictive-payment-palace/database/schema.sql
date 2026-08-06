CREATE DATABASE IF NOT EXISTS predictive_payment_palace;
USE predictive_payment_palace;

CREATE TABLE IF NOT EXISTS businesses (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(150) NOT NULL,
    business_type VARCHAR(100),
    address VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS menu_items (
    id INT PRIMARY KEY AUTO_INCREMENT,
    business_id INT NOT NULL,
    name VARCHAR(150) NOT NULL,
    selling_unit VARCHAR(50) NOT NULL,
    current_prep INT NOT NULL DEFAULT 0,
    portion_note VARCHAR(150) NULL,
    price DECIMAL(10,2) NULL,
    FOREIGN KEY (business_id) REFERENCES businesses(id)
);

CREATE TABLE IF NOT EXISTS users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    business_id INT NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(100),
    FOREIGN KEY (business_id) REFERENCES businesses(id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    business_id INT NOT NULL,
    menu_item_id INT NOT NULL,
    quantity INT NOT NULL,
    meal_period VARCHAR(30),
    sold_at DATETIME NOT NULL,
    FOREIGN KEY (business_id) REFERENCES businesses(id),
    FOREIGN KEY (menu_item_id) REFERENCES menu_items(id)
);

CREATE TABLE IF NOT EXISTS ingredients (
    id INT PRIMARY KEY AUTO_INCREMENT,
    business_id INT NOT NULL,
    name VARCHAR(150) NOT NULL,
    inventory_unit VARCHAR(50) NOT NULL,
    current_quantity DECIMAL(10,2),
    FOREIGN KEY (business_id) REFERENCES businesses(id)
);

CREATE TABLE IF NOT EXISTS recipes (
    id INT PRIMARY KEY AUTO_INCREMENT,
    menu_item_id INT NOT NULL,
    ingredient_id INT NOT NULL,
    amount_per_serving DECIMAL(10,4) NOT NULL,
    FOREIGN KEY (menu_item_id) REFERENCES menu_items(id),
    FOREIGN KEY (ingredient_id) REFERENCES ingredients(id)
);

CREATE TABLE IF NOT EXISTS supplier_packages (
    id INT PRIMARY KEY AUTO_INCREMENT,
    ingredient_id INT NOT NULL,
    supplier_name VARCHAR(150),
    package_unit VARCHAR(50),
    quantity_per_package DECIMAL(10,2),
    package_cost DECIMAL(10,2),
    FOREIGN KEY (ingredient_id) REFERENCES ingredients(id)
);

CREATE INDEX idx_transactions_lookup ON transactions (business_id, menu_item_id, meal_period, sold_at);

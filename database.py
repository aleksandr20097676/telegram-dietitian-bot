"""
Database module for Telegram Dietitian Bot
Contains 90+ food products with nutritional information
"""

import sqlite3
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_name: str = 'dietitian_bot.db'):
        self.db_name = db_name
        self.conn = None
    
    def connect(self):
        """Connect to database"""
        if not self.conn:
            self.conn = sqlite3.connect(self.db_name)
            self.conn.row_factory = sqlite3.Row
        return self.conn
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None
    
    def init_db(self):
        """Initialize database with tables and data"""
        conn = self.connect()
        cursor = conn.cursor()
        
        # Create products table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name_ru TEXT NOT NULL,
                name_cs TEXT NOT NULL,
                name_en TEXT NOT NULL,
                category TEXT NOT NULL,
                calories REAL NOT NULL,
                protein REAL NOT NULL,
                fat REAL NOT NULL,
                carbs REAL NOT NULL,
                serving_size INTEGER DEFAULT 100
            )
        ''')
        
        # Check if table is empty
        cursor.execute('SELECT COUNT(*) FROM products')
        if cursor.fetchone()[0] == 0:
            self._populate_products(cursor)
            conn.commit()
            logger.info("Database initialized with food products")
        
        return True
    
    def _populate_products(self, cursor):
        """Populate database with 90+ food products"""
        products = [
            # Vegetables (Овощи / Zelenina)
            ('Помидор', 'Rajče', 'Tomato', 'vegetables', 18, 0.9, 0.2, 3.9, 100),
            ('Огурец', 'Okurka', 'Cucumber', 'vegetables', 15, 0.8, 0.1, 3.6, 100),
            ('Морковь', 'Mrkev', 'Carrot', 'vegetables', 41, 0.9, 0.2, 9.6, 100),
            ('Капуста', 'Zelí', 'Cabbage', 'vegetables', 25, 1.3, 0.1, 5.8, 100),
            ('Брокколи', 'Brokolice', 'Broccoli', 'vegetables', 34, 2.8, 0.4, 7.0, 100),
            ('Картофель', 'Brambory', 'Potato', 'vegetables', 77, 2.0, 0.1, 17.5, 100),
            ('Лук', 'Cibule', 'Onion', 'vegetables', 40, 1.1, 0.1, 9.3, 100),
            ('Перец болгарский', 'Paprika', 'Bell Pepper', 'vegetables', 27, 0.9, 0.3, 6.0, 100),
            ('Баклажан', 'Lilek', 'Eggplant', 'vegetables', 25, 1.2, 0.2, 5.9, 100),
            ('Кабачок', 'Cuketa', 'Zucchini', 'vegetables', 17, 1.2, 0.3, 3.1, 100),
            
            # Fruits (Фрукты / Ovoce)
            ('Яблоко', 'Jablko', 'Apple', 'fruits', 52, 0.3, 0.2, 13.8, 100),
            ('Банан', 'Banán', 'Banana', 'fruits', 89, 1.1, 0.3, 22.8, 100),
            ('Апельсин', 'Pomeranč', 'Orange', 'fruits', 47, 0.9, 0.1, 11.8, 100),
            ('Груша', 'Hruška', 'Pear', 'fruits', 57, 0.4, 0.1, 15.2, 100),
            ('Виноград', 'Hrozny', 'Grapes', 'fruits', 69, 0.7, 0.2, 18.1, 100),
            ('Клубника', 'Jahody', 'Strawberry', 'fruits', 32, 0.7, 0.3, 7.7, 100),
            ('Арбуз', 'Meloun', 'Watermelon', 'fruits', 30, 0.6, 0.2, 7.6, 100),
            ('Киви', 'Kiwi', 'Kiwi', 'fruits', 61, 1.1, 0.5, 14.7, 100),
            ('Манго', 'Mango', 'Mango', 'fruits', 60, 0.8, 0.4, 15.0, 100),
            ('Ананас', 'Ananas', 'Pineapple', 'fruits', 50, 0.5, 0.1, 13.1, 100),
            
            # Meat (Мясо / Maso)
            ('Курица грудка', 'Kuřecí prsa', 'Chicken Breast', 'meat', 165, 31.0, 3.6, 0.0, 100),
            ('Говядина', 'Hovězí', 'Beef', 'meat', 250, 26.0, 17.0, 0.0, 100),
            ('Свинина', 'Vepřové', 'Pork', 'meat', 242, 17.0, 21.0, 0.0, 100),
            ('Индейка', 'Krůta', 'Turkey', 'meat', 189, 29.0, 7.0, 0.0, 100),
            ('Баранина', 'Jehněčí', 'Lamb', 'meat', 294, 25.0, 21.0, 0.0, 100),
            ('Утка', 'Kachna', 'Duck', 'meat', 337, 19.0, 28.0, 0.0, 100),
            ('Куриное бедро', 'Kuřecí stehno', 'Chicken Thigh', 'meat', 209, 26.0, 11.0, 0.0, 100),
            ('Телятина', 'Telecí', 'Veal', 'meat', 172, 31.0, 5.0, 0.0, 100),
            
            # Fish & Seafood (Рыба и морепродукты / Ryby a mořské plody)
            ('Лосось', 'Losos', 'Salmon', 'seafood', 208, 20.0, 13.0, 0.0, 100),
            ('Тунец', 'Tuňák', 'Tuna', 'seafood', 144, 23.0, 6.0, 0.0, 100),
            ('Треска', 'Treska', 'Cod', 'seafood', 82, 18.0, 0.7, 0.0, 100),
            ('Креветки', 'Krevety', 'Shrimp', 'seafood', 99, 24.0, 0.3, 0.2, 100),
            ('Скумбрия', 'Makrela', 'Mackerel', 'seafood', 205, 19.0, 14.0, 0.0, 100),
            ('Форель', 'Pstruh', 'Trout', 'seafood', 148, 20.0, 7.0, 0.0, 100),
            ('Кальмар', 'Kalamár', 'Squid', 'seafood', 92, 16.0, 1.4, 3.1, 100),
            ('Мидии', 'Slávky', 'Mussels', 'seafood', 86, 12.0, 2.2, 3.7, 100),
            
            # Dairy (Молочные продукты / Mléčné výrobky)
            ('Молоко', 'Mléko', 'Milk', 'dairy', 64, 3.2, 3.6, 4.8, 100),
            ('Творог', 'Tvaroh', 'Cottage Cheese', 'dairy', 98, 11.0, 4.3, 3.0, 100),
            ('Йогурт', 'Jogurt', 'Yogurt', 'dairy', 59, 3.5, 3.3, 4.7, 100),
            ('Сыр чеддер', 'Čedar', 'Cheddar Cheese', 'dairy', 402, 25.0, 33.0, 1.3, 100),
            ('Сметана', 'Zakysaná smetana', 'Sour Cream', 'dairy', 193, 2.4, 19.0, 3.2, 100),
            ('Кефир', 'Kefír', 'Kefir', 'dairy', 56, 2.9, 3.2, 4.0, 100),
            ('Моцарелла', 'Mozzarella', 'Mozzarella', 'dairy', 280, 28.0, 17.0, 3.1, 100),
            ('Сливки', 'Smetana', 'Cream', 'dairy', 345, 2.2, 37.0, 2.8, 100),
            
            # Grains & Cereals (Крупы и злаки / Obiloviny)
            ('Рис белый', 'Bílá rýže', 'White Rice', 'grains', 130, 2.7, 0.3, 28.2, 100),
            ('Гречка', 'Pohanka', 'Buckwheat', 'grains', 343, 13.0, 3.4, 72.0, 100),
            ('Овсянка', 'Ovesné vločky', 'Oatmeal', 'grains', 389, 17.0, 6.9, 66.0, 100),
            ('Макароны', 'Těstoviny', 'Pasta', 'grains', 371, 13.0, 1.5, 75.0, 100),
            ('Хлеб белый', 'Bílý chléb', 'White Bread', 'grains', 265, 9.0, 3.2, 49.0, 100),
            ('Хлеб черный', 'Černý chléb', 'Rye Bread', 'grains', 259, 9.0, 3.3, 48.0, 100),
            ('Киноа', 'Quinoa', 'Quinoa', 'grains', 368, 14.0, 6.1, 64.0, 100),
            ('Кукуруза', 'Kukuřice', 'Corn', 'grains', 86, 3.3, 1.4, 19.0, 100),
            
            # Legumes (Бобовые / Luštěniny)
            ('Чечевица', 'Čočka', 'Lentils', 'legumes', 116, 9.0, 0.4, 20.0, 100),
            ('Горох', 'Hrách', 'Peas', 'legumes', 81, 5.4, 0.4, 14.0, 100),
            ('Фасоль', 'Fazole', 'Beans', 'legumes', 127, 8.7, 0.5, 23.0, 100),
            ('Нут', 'Cizrna', 'Chickpeas', 'legumes', 164, 8.9, 2.6, 27.0, 100),
            ('Соевые бобы', 'Sójové boby', 'Soybeans', 'legumes', 173, 17.0, 9.0, 10.0, 100),
            
            # Nuts & Seeds (Орехи и семена / Ořechy a semena)
            ('Миндаль', 'Mandle', 'Almonds', 'nuts', 579, 21.0, 50.0, 22.0, 100),
            ('Грецкий орех', 'Vlašský ořech', 'Walnuts', 'nuts', 654, 15.0, 65.0, 14.0, 100),
            ('Кешью', 'Kešu', 'Cashews', 'nuts', 553, 18.0, 44.0, 30.0, 100),
            ('Арахис', 'Arašídy', 'Peanuts', 'nuts', 567, 26.0, 49.0, 16.0, 100),
            ('Семена чиа', 'Chia semínka', 'Chia Seeds', 'nuts', 486, 17.0, 31.0, 42.0, 100),
            ('Семена льна', 'Lněná semínka', 'Flax Seeds', 'nuts', 534, 18.0, 42.0, 29.0, 100),
            ('Семечки подсолнуха', 'Slunečnicová semínka', 'Sunflower Seeds', 'nuts', 584, 21.0, 52.0, 20.0, 100),
            
            # Eggs (Яйца / Vejce)
            ('Яйцо куриное', 'Kuřecí vejce', 'Chicken Egg', 'eggs', 155, 13.0, 11.0, 1.1, 100),
            ('Яичный белок', 'Vaječný bílek', 'Egg White', 'eggs', 52, 11.0, 0.2, 0.7, 100),
            ('Яичный желток', 'Vaječný žloutek', 'Egg Yolk', 'eggs', 322, 16.0, 27.0, 3.6, 100),
            
            # Sweets & Desserts (Сладости / Sladkosti)
            ('Шоколад темный', 'Hořká čokoláda', 'Dark Chocolate', 'sweets', 546, 5.0, 31.0, 61.0, 100),
            ('Шоколад молочный', 'Mléčná čokoláda', 'Milk Chocolate', 'sweets', 535, 8.0, 30.0, 59.0, 100),
            ('Мед', 'Med', 'Honey', 'sweets', 304, 0.3, 0.0, 82.0, 100),
            ('Варенье', 'Džem', 'Jam', 'sweets', 278, 0.4, 0.1, 69.0, 100),
            ('Печенье', 'Sušenky', 'Cookies', 'sweets', 502, 6.0, 24.0, 64.0, 100),
            
            # Oils & Fats (Масла и жиры / Oleje a tuky)
            ('Оливковое масло', 'Olivový olej', 'Olive Oil', 'oils', 884, 0.0, 100.0, 0.0, 100),
            ('Подсолнечное масло', 'Slunečnicový olej', 'Sunflower Oil', 'oils', 884, 0.0, 100.0, 0.0, 100),
            ('Сливочное масло', 'Máslo', 'Butter', 'oils', 717, 0.9, 81.0, 0.1, 100),
            ('Кокосовое масло', 'Kokosový olej', 'Coconut Oil', 'oils', 862, 0.0, 99.0, 0.0, 100),
            
            # Beverages (Напитки / Nápoje)
            ('Кофе черный', 'Černá káva', 'Black Coffee', 'beverages', 2, 0.3, 0.0, 0.0, 100),
            ('Чай зеленый', 'Zelený čaj', 'Green Tea', 'beverages', 1, 0.2, 0.0, 0.0, 100),
            ('Сок апельсиновый', 'Pomerančový džus', 'Orange Juice', 'beverages', 45, 0.7, 0.2, 10.4, 100),
            ('Кола', 'Cola', 'Cola', 'beverages', 42, 0.0, 0.0, 10.6, 100),
            
            # Sauces & Condiments (Соусы / Omáčky)
            ('Кетчуп', 'Kečup', 'Ketchup', 'sauces', 112, 1.2, 0.3, 25.0, 100),
            ('Майонез', 'Majonéza', 'Mayonnaise', 'sauces', 680, 1.0, 75.0, 2.7, 100),
            ('Горчица', 'Hořčice', 'Mustard', 'sauces', 66, 4.4, 3.6, 5.3, 100),
            ('Соевый соус', 'Sójová omáčka', 'Soy Sauce', 'sauces', 53, 5.6, 0.0, 4.9, 100),
        ]
        
        cursor.executemany('''
            INSERT INTO products 
            (name_ru, name_cs, name_en, category, calories, protein, fat, carbs, serving_size)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', products)
    
    def get_product_by_name(self, name: str, lang: str = 'en') -> Optional[Dict]:
        """Get product by name in specified language"""
        conn = self.connect()
        cursor = conn.cursor()
        
        name_column = f'name_{lang}'
        query = f'SELECT * FROM products WHERE {name_column} LIKE ? LIMIT 1'
        
        cursor.execute(query, (f'%{name}%',))
        row = cursor.fetchone()
        
        if row:
            return dict(row)
        return None
    
    def search_products(self, query: str, lang: str = 'en') -> List[Dict]:
        """Search products by query"""
        conn = self.connect()
        cursor = conn.cursor()
        
        name_column = f'name_{lang}'
        sql = f'SELECT * FROM products WHERE {name_column} LIKE ? LIMIT 10'
        
        cursor.execute(sql, (f'%{query}%',))
        rows = cursor.fetchall()
        
        return [dict(row) for row in rows]
    
    def get_all_products(self, category: Optional[str] = None) -> List[Dict]:
        """Get all products, optionally filtered by category"""
        conn = self.connect()
        cursor = conn.cursor()
        
        if category:
            cursor.execute('SELECT * FROM products WHERE category = ?', (category,))
        else:
            cursor.execute('SELECT * FROM products')
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

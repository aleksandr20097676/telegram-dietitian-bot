"""
Food Database - 90+ products with nutritional information
"""

FOOD_DATABASE = {
    # Vegetables
    "Tomato": {"calories": 18, "protein": 0.9, "fat": 0.2, "carbs": 3.9, "portion": "100g"},
    "Cucumber": {"calories": 15, "protein": 0.8, "fat": 0.1, "carbs": 3.6, "portion": "100g"},
    "Carrot": {"calories": 41, "protein": 0.9, "fat": 0.2, "carbs": 9.6, "portion": "100g"},
    "Cabbage": {"calories": 25, "protein": 1.3, "fat": 0.1, "carbs": 5.8, "portion": "100g"},
    "Broccoli": {"calories": 34, "protein": 2.8, "fat": 0.4, "carbs": 7.0, "portion": "100g"},
    "Potato": {"calories": 77, "protein": 2.0, "fat": 0.1, "carbs": 17.5, "portion": "100g"},
    "Onion": {"calories": 40, "protein": 1.1, "fat": 0.1, "carbs": 9.3, "portion": "100g"},
    "Bell Pepper": {"calories": 27, "protein": 0.9, "fat": 0.3, "carbs": 6.0, "portion": "100g"},
    "Eggplant": {"calories": 25, "protein": 1.2, "fat": 0.2, "carbs": 5.9, "portion": "100g"},
    "Zucchini": {"calories": 17, "protein": 1.2, "fat": 0.3, "carbs": 3.1, "portion": "100g"},
    
    # Fruits
    "Apple": {"calories": 52, "protein": 0.3, "fat": 0.2, "carbs": 13.8, "portion": "100g"},
    "Banana": {"calories": 89, "protein": 1.1, "fat": 0.3, "carbs": 22.8, "portion": "100g"},
    "Orange": {"calories": 47, "protein": 0.9, "fat": 0.1, "carbs": 11.8, "portion": "100g"},
    "Pear": {"calories": 57, "protein": 0.4, "fat": 0.1, "carbs": 15.2, "portion": "100g"},
    "Grapes": {"calories": 69, "protein": 0.7, "fat": 0.2, "carbs": 18.1, "portion": "100g"},
    "Strawberry": {"calories": 32, "protein": 0.7, "fat": 0.3, "carbs": 7.7, "portion": "100g"},
    "Watermelon": {"calories": 30, "protein": 0.6, "fat": 0.2, "carbs": 7.6, "portion": "100g"},
    "Kiwi": {"calories": 61, "protein": 1.1, "fat": 0.5, "carbs": 14.7, "portion": "100g"},
    "Mango": {"calories": 60, "protein": 0.8, "fat": 0.4, "carbs": 15.0, "portion": "100g"},
    "Pineapple": {"calories": 50, "protein": 0.5, "fat": 0.1, "carbs": 13.1, "portion": "100g"},
    
    # Meat
    "Chicken Breast": {"calories": 165, "protein": 31.0, "fat": 3.6, "carbs": 0.0, "portion": "100g"},
    "Beef": {"calories": 250, "protein": 26.0, "fat": 17.0, "carbs": 0.0, "portion": "100g"},
    "Pork": {"calories": 242, "protein": 17.0, "fat": 21.0, "carbs": 0.0, "portion": "100g"},
    "Turkey": {"calories": 189, "protein": 29.0, "fat": 7.0, "carbs": 0.0, "portion": "100g"},
    "Lamb": {"calories": 294, "protein": 25.0, "fat": 21.0, "carbs": 0.0, "portion": "100g"},
    "Duck": {"calories": 337, "protein": 19.0, "fat": 28.0, "carbs": 0.0, "portion": "100g"},
    "Chicken Thigh": {"calories": 209, "protein": 26.0, "fat": 11.0, "carbs": 0.0, "portion": "100g"},
    "Veal": {"calories": 172, "protein": 31.0, "fat": 5.0, "carbs": 0.0, "portion": "100g"},
    
    # Fish & Seafood
    "Salmon": {"calories": 208, "protein": 20.0, "fat": 13.0, "carbs": 0.0, "portion": "100g"},
    "Tuna": {"calories": 144, "protein": 23.0, "fat": 6.0, "carbs": 0.0, "portion": "100g"},
    "Cod": {"calories": 82, "protein": 18.0, "fat": 0.7, "carbs": 0.0, "portion": "100g"},
    "Shrimp": {"calories": 99, "protein": 24.0, "fat": 0.3, "carbs": 0.2, "portion": "100g"},
    "Mackerel": {"calories": 205, "protein": 19.0, "fat": 14.0, "carbs": 0.0, "portion": "100g"},
    "Trout": {"calories": 148, "protein": 20.0, "fat": 7.0, "carbs": 0.0, "portion": "100g"},
    "Squid": {"calories": 92, "protein": 16.0, "fat": 1.4, "carbs": 3.1, "portion": "100g"},
    "Mussels": {"calories": 86, "protein": 12.0, "fat": 2.2, "carbs": 3.7, "portion": "100g"},
    
    # Dairy
    "Milk": {"calories": 64, "protein": 3.2, "fat": 3.6, "carbs": 4.8, "portion": "100ml"},
    "Cottage Cheese": {"calories": 98, "protein": 11.0, "fat": 4.3, "carbs": 3.0, "portion": "100g"},
    "Yogurt": {"calories": 59, "protein": 3.5, "fat": 3.3, "carbs": 4.7, "portion": "100g"},
    "Cheddar Cheese": {"calories": 402, "protein": 25.0, "fat": 33.0, "carbs": 1.3, "portion": "100g"},
    "Sour Cream": {"calories": 193, "protein": 2.4, "fat": 19.0, "carbs": 3.2, "portion": "100g"},
    "Kefir": {"calories": 56, "protein": 2.9, "fat": 3.2, "carbs": 4.0, "portion": "100ml"},
    "Mozzarella": {"calories": 280, "protein": 28.0, "fat": 17.0, "carbs": 3.1, "portion": "100g"},
    "Cream": {"calories": 345, "protein": 2.2, "fat": 37.0, "carbs": 2.8, "portion": "100ml"},
    
    # Grains & Cereals
    "White Rice": {"calories": 130, "protein": 2.7, "fat": 0.3, "carbs": 28.2, "portion": "100g cooked"},
    "Buckwheat": {"calories": 343, "protein": 13.0, "fat": 3.4, "carbs": 72.0, "portion": "100g dry"},
    "Oatmeal": {"calories": 389, "protein": 17.0, "fat": 6.9, "carbs": 66.0, "portion": "100g dry"},
    "Pasta": {"calories": 371, "protein": 13.0, "fat": 1.5, "carbs": 75.0, "portion": "100g dry"},
    "White Bread": {"calories": 265, "protein": 9.0, "fat": 3.2, "carbs": 49.0, "portion": "100g"},
    "Rye Bread": {"calories": 259, "protein": 9.0, "fat": 3.3, "carbs": 48.0, "portion": "100g"},
    "Quinoa": {"calories": 368, "protein": 14.0, "fat": 6.1, "carbs": 64.0, "portion": "100g dry"},
    "Corn": {"calories": 86, "protein": 3.3, "fat": 1.4, "carbs": 19.0, "portion": "100g"},
    
    # Legumes
    "Lentils": {"calories": 116, "protein": 9.0, "fat": 0.4, "carbs": 20.0, "portion": "100g cooked"},
    "Peas": {"calories": 81, "protein": 5.4, "fat": 0.4, "carbs": 14.0, "portion": "100g"},
    "Beans": {"calories": 127, "protein": 8.7, "fat": 0.5, "carbs": 23.0, "portion": "100g cooked"},
    "Chickpeas": {"calories": 164, "protein": 8.9, "fat": 2.6, "carbs": 27.0, "portion": "100g cooked"},
    "Soybeans": {"calories": 173, "protein": 17.0, "fat": 9.0, "carbs": 10.0, "portion": "100g cooked"},
    
    # Nuts & Seeds
    "Almonds": {"calories": 579, "protein": 21.0, "fat": 50.0, "carbs": 22.0, "portion": "100g"},
    "Walnuts": {"calories": 654, "protein": 15.0, "fat": 65.0, "carbs": 14.0, "portion": "100g"},
    "Cashews": {"calories": 553, "protein": 18.0, "fat": 44.0, "carbs": 30.0, "portion": "100g"},
    "Peanuts": {"calories": 567, "protein": 26.0, "fat": 49.0, "carbs": 16.0, "portion": "100g"},
    "Chia Seeds": {"calories": 486, "protein": 17.0, "fat": 31.0, "carbs": 42.0, "portion": "100g"},
    "Flax Seeds": {"calories": 534, "protein": 18.0, "fat": 42.0, "carbs": 29.0, "portion": "100g"},
    "Sunflower Seeds": {"calories": 584, "protein": 21.0, "fat": 52.0, "carbs": 20.0, "portion": "100g"},
    
    # Eggs
    "Chicken Egg": {"calories": 155, "protein": 13.0, "fat": 11.0, "carbs": 1.1, "portion": "100g (2 eggs)"},
    "Egg White": {"calories": 52, "protein": 11.0, "fat": 0.2, "carbs": 0.7, "portion": "100g"},
    "Egg Yolk": {"calories": 322, "protein": 16.0, "fat": 27.0, "carbs": 3.6, "portion": "100g"},
    
    # Sweets & Desserts
    "Dark Chocolate": {"calories": 546, "protein": 5.0, "fat": 31.0, "carbs": 61.0, "portion": "100g"},
    "Milk Chocolate": {"calories": 535, "protein": 8.0, "fat": 30.0, "carbs": 59.0, "portion": "100g"},
    "Honey": {"calories": 304, "protein": 0.3, "fat": 0.0, "carbs": 82.0, "portion": "100g"},
    "Jam": {"calories": 278, "protein": 0.4, "fat": 0.1, "carbs": 69.0, "portion": "100g"},
    "Cookies": {"calories": 502, "protein": 6.0, "fat": 24.0, "carbs": 64.0, "portion": "100g"},
    
    # Oils & Fats
    "Olive Oil": {"calories": 884, "protein": 0.0, "fat": 100.0, "carbs": 0.0, "portion": "100ml"},
    "Sunflower Oil": {"calories": 884, "protein": 0.0, "fat": 100.0, "carbs": 0.0, "portion": "100ml"},
    "Butter": {"calories": 717, "protein": 0.9, "fat": 81.0, "carbs": 0.1, "portion": "100g"},
    "Coconut Oil": {"calories": 862, "protein": 0.0, "fat": 99.0, "carbs": 0.0, "portion": "100ml"},
}

"""
Simple test file for agent workflow testing.
This file intentionally has basic error handling that could be improved.
"""

def divide_numbers(a, b):
    # TODO: Add better error handling
    return a / b

def fetch_user_data(user_id):
    # TODO: Add validation and error handling
    data = {"id": user_id, "name": "Test User"}
    return data

def process_data(data):
    # TODO: Add error handling for missing keys
    result = data["value"] * 2
    return result

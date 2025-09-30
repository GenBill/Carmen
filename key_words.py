import os
import re
from get_stock_list import get_nasdaq_stock_symbols

KEY_WORDS = ['@所有人', '买', '卖', '入', '出']


def resort_stock_list(upper_message, stock_list):
    stock_positions = []
    for stock in stock_list:
        index = upper_message.find(stock)
        # Add check for index != -1 for robustness, though you expect it to be found
        if index != -1:
            stock_positions.append((index, stock))
        # else: # Optional: handle case where stock is unexpectedly not found
            # print(f"Warning: Stock '{stock}' from list not found in message.")

    stock_positions.sort(key=lambda item: item[0])
    # Return the list of (index, stock) tuples sorted by index
    return stock_positions

def analysis_message(upper_message, stock_list):
    # Get stock positions sorted by appearance index
    stock_positions = resort_stock_list(upper_message, stock_list)

    # Define action keywords and map them to 'BUY' or 'SELL'
    ACTION_MAP = {'买入': 'BUY', '买': 'BUY', '卖出': 'SELL', '卖': 'SELL'}
    # Create an uppercase version of the map keys for searching
    UPPER_ACTION_MAP = {k.upper(): v for k, v in ACTION_MAP.items()}
    # Sort uppercase keywords by length descending
    UPPER_KEYWORDS_SORTED = sorted(UPPER_ACTION_MAP.keys(), key=len, reverse=True)

    # List to store all found items (actions and stocks) with their positions
    found_items = []

    # Find all occurrences of action keywords in the message
    for upper_keyword in UPPER_KEYWORDS_SORTED:
        # Get the corresponding action ('BUY' or 'SELL')
        action = UPPER_ACTION_MAP[upper_keyword]
        start = 0
        while True:
            # Search for the uppercase keyword in the uppercase message
            index = upper_message.find(upper_keyword, start)
            if index == -1:
                break
            found_items.append((index, 'ACTION', action))
            # Update start position
            start = index + len(upper_keyword)

    # Add the positions of the stocks (already sorted by appearance)
    for index, stock in stock_positions:
        found_items.append((index, 'STOCK', stock))

    # Sort all found items (actions and stocks) by their index in the message
    found_items.sort(key=lambda item: item[0])

    # Dictionary to store the final mapping of stock -> action
    results = {}
    # Variable to hold the most recently encountered action
    last_action = None

    # Process the sorted items to link actions to the stocks that follow them
    for index, item_type, value in found_items:
        if item_type == 'ACTION':
            last_action = value
        elif item_type == 'STOCK':
            if last_action != None and value not in results:
                results[value] = last_action

    # Return the dictionary containing {stock_code: action} pairs
    return results

def key_word_check(message):
    
    if '\n引用' in message:
        return 0
    
    # Convert message to uppercase ONCE here
    upper_message = message.upper()
    score = 0
    # Convert KEY_WORDS to upper once
    upper_key_words = [key.upper() for key in KEY_WORDS]
    for upper_key in upper_key_words:
        if upper_key in upper_message:
            score += 1

    # Pass upper_message to stock_code_check
    stock_list = stock_code_check(upper_message)
    if len(stock_list) > 0:
        # Pass upper_message to analysis_message
        meaning = analysis_message(upper_message, stock_list)
        print(meaning)
        return score * len(stock_list)
    else:
        return 0


def stock_code_check(upper_message):
    stock_file = 'nasdaq_stock_symbols.txt'
    if not os.path.exists(stock_file):
        try:
            get_nasdaq_stock_symbols()
            print(f"Generated {stock_file}")
        except ImportError:
            print(f"Error: Could not import get_nasdaq_stock_symbols from stock_list.")
            return []
        except Exception as e:
            print(f"Error generating {stock_file}: {e}")
            return []
        if not os.path.exists(stock_file):
            print(f"Error: {stock_file} still not found after generation attempt.")
            return []

    try:
        with open(stock_file, 'r') as f:
            stock_codes = [code.strip().upper() for code in f.readlines()]
    except IOError as e:
        print(f"Error reading {stock_file}: {e}")
        return []

    found_stocks = []
    for code in stock_codes:
        if not code: continue
        pattern = r'(?<![A-Za-z0-9])' + re.escape(code) + r'(?![A-Za-z0-9])'
        if re.search(pattern, upper_message):
            found_stocks.append(code)

    return list(set(found_stocks))


if __name__ == '__main__':

    # Test cases
    print("Testing: 'nvda'")
    print(key_word_check('nvda')) # Should find NVDA, score depends on keywords

    print("\nTesting: '@所有人 买入nvda'") # Using regular space
    print(key_word_check('@所有人 买入nvda')) # Should find NVDA, score higher

    print("\nTesting: 'buy nvda and sell coin'")
    print(key_word_check('buy nvda and sell coin')) # Should find NVDA and COIN (if COIN is in list)

    print("\nTesting: '买入nvda卖出coin'")
    print(key_word_check('买入nvda卖出coin')) # Should find NVDA and COIN

    print("\nTesting: '买入nvda卖出coin和tem'")
    print(key_word_check('买入nvda卖出coin和tem')) # Should find NVDA and COIN

    print("\nTesting: 'anvdat test'")
    print(key_word_check('anvdat test')) # Should NOT find NVDA





import numpy as np
import copy


class HFTMarketEnvironment:

    
    def __init__(self, params):
        self.bid_ask = params.get("bid_ask", None)
        self.trades = params.get("trades", None)
        self.balance = params.get("balance", None)
        self.cancel_frequency = params.get("cancel_frequency", 10)
        self.open_orders = []
        self.long_inventory = []
        self.short_inventory = []
        self.avg_buy_price = []
        self.avg_sell_price = []
        self.inventory = 0
        self.inventory_history = []
        self.cash_balance = 0
        self.cash_balance_history = []
        self.pnl = []

    def reset(self):
        self.data_pointer = self.__reset_pointer()
        self.open_orders = []
        self.long_inventory = []
        self.short_inventory = []
        self.avg_buy_price = []
        self.avg_sell_price = []
        self.inventory = 0
        self.cash_balance = 0
        self.pnl = []

        state = {
            "bid_ask": self.__get_bid_ask(),
            "trades": self.__get_trades(),
            "long_inventory": self.long_inventory,
            "short_inventory": self.short_inventory,
            "cash_balance": self.cash_balance,
            "inventory": 0,
            "avg_buy_price": None,
            "avg_sell_price": None,
            "realized_pnl": 0,
            "unrealized_pnl": 0
        }
        return state, False

    def step(self, action):
        done = False
        if not self.__advance_pointer():
            done = True
        # check existing limit orders for execution
        executed_orders_k = self._check_execution()
        # cancel remaining limit orders
        if self.data_pointer % self.cancel_frequency == 0:
            self._cancel_los()
        # calculate pnl on existing orders
        pnl_dict = self._calculate_realized_pnl(executed_orders_k)
        self.pnl.append(pnl_dict)
        # place limit orders
        if not done:
            self._place_los(action)
        
        state = {
            "bid_ask": self.__get_bid_ask(),
            "trades": self.__get_trades(),
            "long_inventory": self.long_inventory,
            "short_inventory": self.short_inventory,
            "cash_balance": self.cash_balance,
            "inventory": pnl_dict["inventory"],
            "avg_buy_price": pnl_dict["avg_buy_price"],
            "avg_sell_price": pnl_dict["avg_sell_price"],
            "realized_pnl": pnl_dict["realized_pnl"],
            "unrealized_pnl": pnl_dict["unrealized_pnl"]
        }
        return state, done


    def _place_los(self, los):
        curr_ts = self.__get_current_ts()
        for lo in los:
            if self._is_enough_balance(lo):
                lo["place_time"] = curr_ts
                self.open_orders.append(lo)
        self.open_orders = sorted(self.open_orders, key=lambda d: d["place_time"])


    def _is_enough_balance(self, lo):
        can_place = True
        inventory, cash = self._get_actual_balance()
        if lo["buySell"] == "BUY":
            buy_cost = lo["price"] * lo["quantity"]
            if buy_cost > cash:
                can_place = False
        elif lo["buySell"] == "SELL":
            sell_inv = lo["quantity"]
            if sell_inv > inventory:
                can_place = False
        return can_place
        
            
    def _get_actual_balance(self):
        inventory = self.balance["BTC"] + self.inventory
        cash = self.balance["FDUSD"] + self.cash_balance
        return inventory, cash

    
    def _check_execution(self):
        open_orders = copy.deepcopy(self.open_orders)
        trades = copy.deepcopy(self.__get_trades())
        bid_ask = copy.deepcopy(self.__get_bid_ask())
        executed_orders_k = []
        
        for i, lo in enumerate(open_orders):
            quantity = lo["quantity"]
            price = lo["price"]
            buySell = lo["buySell"]
            if buySell == "BUY":
                # check execution with trades
                for trade in trades:
                    # execution condition by trades
                    if (trade["price"] <= price) and (not np.allclose(trade["quantity"], 0)):
                        executed_quantity = min(quantity, lo["quantity"])
                        trade["quantity"] -= executed_quantity
                        executed_orders_k.append(
                            {
                                "price": lo["price"],
                                "quantity": executed_quantity,
                                "tradeTime": trade["tradeTime"],
                                "buySell": "BUY"
                            }
                        )
                        lo["quantity"] -= executed_quantity
                        if np.allclose(lo["quantity"], 0):
                            break

            if buySell == "SELL":
                # check execution with trades
                for trade in trades:
                    # execution condition
                    if (trade["price"] >= price) and (not np.allclose(trade["quantity"], 0)):
                        executed_quantity = min(quantity, lo["quantity"])
                        trade["quantity"] -= executed_quantity
                        executed_orders_k.append(
                            {
                                "price": lo["price"],
                                "quantity": executed_quantity,
                                "tradeTime": trade["tradeTime"],
                                "buySell": "SELL"
                            }
                        )
                        lo["quantity"] -= executed_quantity
                        if np.allclose(lo["quantity"], 0):
                            break

        for lo_modified, lo_original in zip(open_orders, self.open_orders):
            lo_original["quantity"] = lo_modified["quantity"]
        for lo in self.open_orders:
            if np.allclose(lo["quantity"], 0):
                self.open_orders.remove(lo)
        return executed_orders_k
                

    def _cancel_los(self):
        self.open_orders = []
        

    def _calculate_realized_pnl(self, executed_orders):
        bid_ask = self.__get_bid_ask()
        bid_price, ask_price = bid_ask[-1]["bid_price"], bid_ask[-1]["ask_price"]
    
        # Function to calculate weighted average price
        def weighted_average_price(inventory):
            total_qty = sum([qty for qty, _ in inventory])
            if np.allclose(total_qty, 0):
                return 0
            return sum([qty * price for qty, price in inventory]) / total_qty
        total_realized_pnl = 0
        for i, order in enumerate(executed_orders):
            if order['buySell'] == 'BUY':
                buy_quantity = order['quantity']
                buy_cost = buy_quantity * order['price']
                while buy_quantity > 0 and self.short_inventory:
                    short_qty, short_price = self.short_inventory[0]
                    trade_qty = min(-short_qty, buy_quantity)
                    buy_quantity -= trade_qty
                    self.short_inventory[0] = (short_qty + trade_qty, short_price)
    
                    if self.short_inventory[0][0] == 0:
                        self.short_inventory.pop(0)
    
                    pnl = trade_qty * (short_price - order['price'])
                    total_realized_pnl += pnl
    
                # Add remaining quantity to long inventory
                if buy_quantity > 0:
                    self.long_inventory.append((buy_quantity, order['price']))
                self.cash_balance -= buy_cost
    
            elif order['buySell'] == 'SELL':
                sell_quantity = order['quantity']
                sell_revenue = sell_quantity * order['price']
                while sell_quantity > 0 and self.long_inventory:
                    long_qty, long_price = self.long_inventory[0]
                    trade_qty = min(long_qty, sell_quantity)
                    sell_quantity -= trade_qty
                    self.long_inventory[0] = (long_qty - trade_qty, long_price)
    
                    if self.long_inventory[0][0] == 0:
                        self.long_inventory.pop(0)
    
                    pnl = trade_qty * (order['price'] - long_price)
                    total_realized_pnl += pnl
    
                if sell_quantity > 0:
                    self.short_inventory.append((-sell_quantity, order['price']))
                self.cash_balance += sell_revenue

        inventory_buy = sum([qty for qty, _ in self.long_inventory])
        inventory_sell = sum([qty for qty, _ in self.short_inventory])
        inventory = inventory_buy + inventory_sell
        avg_buy_price = weighted_average_price(self.long_inventory)
        avg_sell_price = weighted_average_price(self.short_inventory)
        unrealized_pnl = self._calculate_unrealized_pnl(inventory, avg_buy_price, avg_sell_price, bid_price, ask_price)
        pnl_dict = {
            "received_time": bid_ask[-1]["received_time"],
            "inventory_buy": inventory_buy,
            "inventory_sell": inventory_sell,
            "inventory": inventory,
            "cash_balance": self.cash_balance,
            "avg_buy_price": avg_buy_price,
            "avg_sell_price": avg_sell_price,
            "realized_pnl": total_realized_pnl,
            "unrealized_pnl": unrealized_pnl
        }
        self.inventory = inventory
        return pnl_dict
            

    def _calculate_unrealized_pnl(self, inventory, avg_buy_price, avg_sell_price, bid_price, ask_price):
        if inventory > 0:
            return inventory * (bid_price - avg_buy_price)
        elif inventory < 0:
            return abs(inventory) * (avg_sell_price - ask_price)
        else:
            return 0


    def __reset_pointer(self):
        self.periods = list(self.bid_ask.keys())
        return 0
        

    def __advance_pointer(self):
        if (self.data_pointer + 1) == len(self.periods):
            return False
        self.data_pointer += 1
        return True

    
    def __get_bid_ask(self):
        return self.bid_ask[self.periods[self.data_pointer]]

    
    def __get_trades(self):
        return self.trades[self.periods[self.data_pointer]]

    
    def __get_current_ts(self):
        return self.periods[self.data_pointer][0]
    
        
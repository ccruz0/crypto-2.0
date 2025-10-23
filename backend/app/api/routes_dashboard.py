from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.models.user import User
from app.models.watchlist import Watchlist
from app.schemas.watchlist import WatchlistIn, WatchlistOut
from app.deps.auth import get_current_user, get_db
from app.services.market_data_manager import market_data_manager
from app.services.signals.signal_engine import evaluate_signals
from app.services.brokers.base import Exchange

router = APIRouter()

@router.get("/dashboard", response_model=List[WatchlistOut])
def get_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get watchlist with calculated market data and signals"""
    watchlist_items = db.query(Watchlist).filter(Watchlist.user_id == current_user.id).all()
    
    result = []
    for w in watchlist_items:
        try:
            # Get market price
            exchange: Exchange = w.exchange
            price = market_data_manager.get_last_price(exchange, w.symbol)
            
            # Get signals
            signals = evaluate_signals(w.symbol, exchange)
            
            # Calculate buy/sell signals
            buy_signal = signals['rsi'] < 40 and price <= signals['res_down']
            sell_signal = signals['rsi'] > 70 and price >= signals['res_up']
            
            # Create watchlist item with calculated fields
            item = WatchlistOut(
                id=w.id,
                symbol=w.symbol,
                exchange=w.exchange,
                buy_target=w.buy_target,
                take_profit=w.take_profit,
                stop_loss=w.stop_loss,
                order_status=w.order_status,
                order_date=w.order_date,
                purchase_price=w.purchase_price,
                quantity=w.quantity,
                sold=w.sold,
                sell_price=w.sell_price,
                notes=w.notes,
                created_at=w.created_at,
                price=price,
                rsi=signals['rsi'],
                atr=signals['atr'],
                ma50=signals['ma50'],
                ma200=signals['ma200'],
                ema10=signals['ema10'],
                res_up=signals['res_up'],
                res_down=signals['res_down'],
                signals={"buy": buy_signal, "sell": sell_signal}
            )
            result.append(item)
        except Exception as e:
            # If error getting market data, return basic item
            item = WatchlistOut(
                id=w.id,
                symbol=w.symbol,
                exchange=w.exchange,
                buy_target=w.buy_target,
                take_profit=w.take_profit,
                stop_loss=w.stop_loss,
                order_status=w.order_status,
                order_date=w.order_date,
                purchase_price=w.purchase_price,
                quantity=w.quantity,
                sold=w.sold,
                sell_price=w.sell_price,
                notes=w.notes,
                created_at=w.created_at
            )
            result.append(item)
    
    return result

@router.post("/dashboard", response_model=WatchlistOut, status_code=status.HTTP_201_CREATED)
def add_to_dashboard(
    watchlist_in: WatchlistIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add new symbol to watchlist"""
    # Check if symbol already exists for this user
    existing = db.query(Watchlist).filter(
        Watchlist.user_id == current_user.id,
        Watchlist.symbol == watchlist_in.symbol
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Symbol already in watchlist"
        )
    
    watchlist_item = Watchlist(
        user_id=current_user.id,
        symbol=watchlist_in.symbol,
        exchange=watchlist_in.exchange,
        buy_target=watchlist_in.buy_target,
        take_profit=watchlist_in.take_profit,
        stop_loss=watchlist_in.stop_loss
    )
    
    db.add(watchlist_item)
    db.commit()
    db.refresh(watchlist_item)
    
    return watchlist_item

@router.put("/dashboard/{id}", response_model=WatchlistOut)
def update_dashboard(
    id: int,
    watchlist_in: WatchlistIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update watchlist item"""
    watchlist_item = db.query(Watchlist).filter(
        Watchlist.id == id,
        Watchlist.user_id == current_user.id
    ).first()
    
    if not watchlist_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Watchlist item not found"
        )
    
    watchlist_item.symbol = watchlist_in.symbol
    watchlist_item.exchange = watchlist_in.exchange
    watchlist_item.buy_target = watchlist_in.buy_target
    watchlist_item.take_profit = watchlist_in.take_profit
    watchlist_item.stop_loss = watchlist_in.stop_loss
    
    db.commit()
    db.refresh(watchlist_item)
    
    return watchlist_item

@router.delete("/dashboard/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_from_dashboard(
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete watchlist item"""
    watchlist_item = db.query(Watchlist).filter(
        Watchlist.id == id,
        Watchlist.user_id == current_user.id
    ).first()
    
    if not watchlist_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Watchlist item not found"
        )
    
    db.delete(watchlist_item)
    db.commit()
    
    return None

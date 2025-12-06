# Portfolio Loans Feature

## Overview

The portfolio now includes support for tracking borrowed amounts (loans). Loans are automatically **subtracted** from your total portfolio value to show your true net worth.

## How It Works

- **Total Portfolio Value** = Total Assets - Total Borrowed
- Example: If you have $50,000 in assets and $10,000 in loans, your net portfolio value is $40,000

## API Endpoints

### Get All Loans
```bash
GET /api/loans
```

Returns list of active loans with their USD values.

### Add a Loan
```bash
POST /api/loans
Content-Type: application/json

{
  "currency": "USDT",
  "borrowed_amount": 5000,
  "borrowed_usd_value": 5000,  # Optional, will be calculated if not provided
  "interest_rate": 8.5,         # Optional, annual interest rate in %
  "notes": "Margin loan for trading"  # Optional
}
```

### Update a Loan
```bash
PUT /api/loans/{loan_id}
Content-Type: application/json

{
  "currency": "USDT",
  "borrowed_amount": 6000,
  "interest_rate": 9.0
}
```

### Delete a Loan
```bash
DELETE /api/loans/{loan_id}
```

This marks the loan as inactive (soft delete).

## Examples

### Add a USD loan
```bash
curl -X POST http://localhost:8002/api/loans \
  -H "Content-Type: application/json" \
  -d '{
    "currency": "USDT",
    "borrowed_amount": 10000,
    "interest_rate": 8.0,
    "notes": "Trading margin"
  }'
```

### Add a crypto loan
```bash
curl -X POST http://localhost:8002/api/loans \
  -H "Content-Type: application/json" \
  -d '{
    "currency": "BTC",
    "borrowed_amount": 0.5,
    "notes": "Borrowed BTC for shorting"
  }'
```

The system will automatically calculate the USD value based on current market prices.

### View all loans
```bash
curl http://localhost:8002/api/loans | jq
```

## Portfolio Display

The portfolio now shows:
- **Total Assets**: Sum of all your holdings
- **Total Borrowed**: Sum of all active loans
- **Net Value**: Total Assets - Total Borrowed (your true net worth)

## Database

Loans are stored in the `portfolio_loans` table with the following fields:
- `id`: Unique identifier
- `currency`: Currency code (BTC, ETH, USDT, etc.)
- `borrowed_amount`: Amount borrowed in that currency
- `borrowed_usd_value`: USD equivalent
- `interest_rate`: Annual interest rate (%)
- `notes`: Optional notes about the loan
- `is_active`: Whether the loan is still active
- `created_at`: When the loan was added
- `updated_at`: When the loan was last updated

## Notes

- Loans are automatically calculated in USD using current market prices
- When you delete a loan, it's marked as inactive (soft delete) for historical records
- The portfolio value displayed on the dashboard automatically includes loan deductions
- If you add a loan in a stablecoin (USD, USDT, USDC), the borrowed_usd_value equals the borrowed_amount
- For crypto loans (BTC, ETH, etc.), the USD value is calculated using current market prices


-- Migration: Create portfolio_loans table
-- Date: 2025-11-07
-- Description: Adds support for tracking borrowed amounts (loans) in the portfolio

CREATE TABLE IF NOT EXISTS portfolio_loans (
    id SERIAL PRIMARY KEY,
    currency VARCHAR(20) NOT NULL,
    borrowed_amount NUMERIC(20, 8) NOT NULL DEFAULT 0,
    borrowed_usd_value FLOAT NOT NULL DEFAULT 0,
    interest_rate FLOAT,
    notes TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create index on currency for faster lookups
CREATE INDEX IF NOT EXISTS idx_portfolio_loans_currency ON portfolio_loans(currency);

-- Create index on is_active for faster queries
CREATE INDEX IF NOT EXISTS idx_portfolio_loans_is_active ON portfolio_loans(is_active);

-- Add comment to table
COMMENT ON TABLE portfolio_loans IS 'Stores borrowed amounts (loans) that should be subtracted from portfolio value';
COMMENT ON COLUMN portfolio_loans.currency IS 'Currency code (e.g., BTC, ETH, USD)';
COMMENT ON COLUMN portfolio_loans.borrowed_amount IS 'Amount borrowed in the currency';
COMMENT ON COLUMN portfolio_loans.borrowed_usd_value IS 'USD value of the borrowed amount';
COMMENT ON COLUMN portfolio_loans.interest_rate IS 'Annual interest rate (%) for the loan';
COMMENT ON COLUMN portfolio_loans.is_active IS 'Whether this loan is still active';


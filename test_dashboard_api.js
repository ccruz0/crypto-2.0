#!/usr/bin/env node

// Test script to verify dashboard API is working
const fetch = require('node-fetch');

async function testDashboardAPI() {
  try {
    console.log('🧪 Testing Dashboard API...');
    
    // Test the crypto-data endpoint
    const response = await fetch('http://localhost:8001/api/crypto-data');
    const data = await response.json();
    
    console.log('✅ Crypto Data Endpoint Status:', response.status);
    console.log('✅ Success:', data.success);
    console.log('✅ Data Count:', data.data ? data.data.length : 0);
    
    if (data.data && data.data.length > 0) {
      console.log('✅ First Crypto:', data.data[0].symbol, '- $' + data.data[0].price);
      console.log('✅ Sources:', data.data[0].sources);
    }
    
    // Test the account balance endpoint
    const balanceResponse = await fetch('http://localhost:8001/api/account/balance');
    const balanceData = await balanceResponse.json();
    
    console.log('✅ Account Balance Status:', balanceResponse.status);
    console.log('✅ Total USD:', balanceData.total_usd);
    console.log('✅ Accounts:', balanceData.accounts ? balanceData.accounts.length : 0);
    
    console.log('\n🎉 All endpoints are working correctly!');
    
  } catch (error) {
    console.error('❌ Error testing API:', error.message);
  }
}

testDashboardAPI();


// Quick test to verify cache logic
const cache = new Map();
const TTL = 30000;

function getCached(symbol) {
  const cached = cache.get(symbol);
  if (cached) {
    const age = Date.now() - cached.timestamp;
    if (age < TTL) {
      console.log(`Cache HIT for ${symbol}`);
      return cached.promise;
    }
    cache.delete(symbol);
  }
  console.log(`Cache MISS for ${symbol}`);
  return null;
}

function setCached(symbol, promise) {
  cache.set(symbol, { promise, timestamp: Date.now() });
  console.log(`Cache SET for ${symbol}`);
}

// Simulate concurrent calls
console.log('Simulating 3 concurrent calls to ALGO_USDT:');
const symbol = 'ALGO_USDT';

// Call 1
const cached1 = getCached(symbol);
if (!cached1) {
  const p1 = Promise.resolve('result1');
  setCached(symbol, p1);
}

// Call 2 (immediately after)
const cached2 = getCached(symbol);
if (!cached2) {
  const p2 = Promise.resolve('result2');
  setCached(symbol, p2);
}

// Call 3 (immediately after)
const cached3 = getCached(symbol);
if (!cached3) {
  const p3 = Promise.resolve('result3');
  setCached(symbol, p3);
}

console.log(`\nResult: ${cache.size} cache entries (should be 1)`);



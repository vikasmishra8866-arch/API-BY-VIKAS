const express = require('express');
const path = require('path');
const app = express();

app.use(express.json());
app.use(express.static(path.join(__dirname, '.')));

// Proxy endpoint to bypass CORS
app.get('/api/vehicle', async (req, res) => {
  const regNo = req.query.vehicle_number;
  try {
    const apiRes = await fetch(`https://randkikichut.vercel.app/?vehicle_number=${encodeURIComponent(regNo)}`);
    const data = await apiRes.json();
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: "Failed to fetch from external API" });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});

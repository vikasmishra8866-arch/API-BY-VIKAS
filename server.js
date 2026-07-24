const express = require('express');
const path = require('path');
const app = express();

// Static files serve karne ke liye
app.use(express.static(path.join(__dirname, '.')));

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Server is running on port ${PORT}`);
});

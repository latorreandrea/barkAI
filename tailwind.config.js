/** @type {import('tailwindcss').Config} */
module.exports = {
  // Every HTML template and every static JS file that mentions utility class
  // names (the chat UI builds message bubbles from JS strings) must be scanned
  // so no used utility is dropped from the compiled stylesheet.
  content: [
    "./templates/**/*.html",
    "./chat/**/*.html",
    "./static/js/**/*.js",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
      colors: {
        brand: {
          50: "#fffbeb",
          100: "#fef3c7",
          200: "#fde68a",
          300: "#fcd34d",
          400: "#fbbf24",
          500: "#f59e0b",
          600: "#d97706",
          700: "#b45309",
        },
      },
    },
  },
  plugins: [],
};

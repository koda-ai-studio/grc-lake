const { minimatch, Minimatch } = require("minimatch-core");

// Legacy ESLint plugins call the module and use makeRe only as a .test predicate.
module.exports = Object.assign((...args) => minimatch(...args), minimatch, {
  makeRe(pattern, options) {
    const matcher = new Minimatch(pattern, options);
    return { test: (path) => matcher.match(path) };
  },
});

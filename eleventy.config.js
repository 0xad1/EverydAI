
export default function (eleventyConfig) {
    eleventyConfig.addPassthroughCopy("src/styles.css");
  
    return {
      pathPrefix: "/EverydAI/",
      dir: {
        input: "src",
        includes: "_includes",
        data: "_data",
        output: "_site"
      },
      templateFormats: ["njk", "md", "html"],
      htmlTemplateEngine: "njk",
      markdownTemplateEngine: "njk"
    };
  }
  
# News feeds

Headlines and summaries from the configured news feeds.

Never the article body: the classifier only ever sees a headline and a summary
anyway, and storing whole articles from commercial outlets buys nothing and
raises a copyright question.

Feeds are polled with a "has this changed?" header, so an unchanged feed costs
one round trip and no parsing.

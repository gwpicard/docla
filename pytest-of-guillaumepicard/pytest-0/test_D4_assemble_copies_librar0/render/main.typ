#import "/lib/theme.typ": colour, page-setup
#import "/components/spark.typ": spark
#import "/components/statement.typ": statement

#show: page-setup.with("slides")
#set text(fill: colour("ink"))

#let comp = json("/composition.json")
#let sec = comp.sections.at(0).props + comp.sections.at(0).content
#spark(sec)
#pagebreak()
#let sec = comp.sections.at(1).props + comp.sections.at(1).content
#statement(sec)

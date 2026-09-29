"""hermes-os -- Antworten von Hermes für den Verlauf im Kontor setzen.

Das Textfeld im Kontor (Kirigami.SelectableLabel, ein TextEdit) setzt Markdown
selbst, kennt aber weder Absatz- noch Zeilenabstand: Absätze, Listen und
Überschriften klebten dicht aneinander, eine längere Antwort las sich wie ein
Editor. Hier übersetzt QTextDocument das Markdown wie das Textfeld, bekommt
dann je Absatz Luft darunter und etwas mehr Zeilenhöhe, und das Kontor zeigt
das Ergebnis als HTML (backend.chatHtml, Main.qml).

Die Schrift bleibt die des Textfelds: Schriftart und -größe aus dem Kopf des
HTML fallen weg. Codeblöcke bleiben eng, Listenpunkte etwas enger als Absätze.
Nur PySide6.QtGui; läuft im Leisten-Symbol und in tests/tray-gui-check.py.
"""
import re

from PySide6.QtGui import QTextBlockFormat, QTextCursor, QTextDocument, QTextFormat

PARAGRAPH_GAP_EM = 0.65     # Luft unter einem Absatz, in Schriftgrößen
LIST_GAP_EM = 0.3           # zwischen zwei Punkten derselben Liste
LIST_INDENT_EM = 1.4        # Einrückung je Listenebene; Qt nähme 40 px, zu viel für eine Blase
LINE_HEIGHT_PERCENT = 106   # auf die natürliche Zeilenhöhe der Schrift


def _is_code(fmt):
    return fmt.nonBreakableLines() or fmt.hasProperty(QTextFormat.Property.BlockCodeFence)


def to_html(markdown, point_size=10.0):
    """Markdown als HTML mit Absatzabständen; point_size ist die Schriftgröße des
    Textfelds, nach ihr richten sich die Abstände."""
    doc = QTextDocument()
    doc.setMarkdown(markdown or "")
    px = max(float(point_size or 10.0), 6.0) * 96 / 72
    gap, list_gap = round(px * PARAGRAPH_GAP_EM), round(px * LIST_GAP_EM)
    step = round(px * LIST_INDENT_EM)
    # Listen: Ebene merken, bevor die Einrückung der Liste auf null geht; die Punkte
    # rücken stattdessen über den linken Rand ein (Qt zeichnet das Aufzählungszeichen
    # vor den Anfang des Textes)
    levels = {}
    block = doc.begin()
    while block.isValid():
        lst = block.textList()
        if lst is not None and lst.objectIndex() not in levels:
            levels[lst.objectIndex()] = max(lst.format().indent(), 1)
        block = block.next()
    cursor = QTextCursor(doc)
    block = doc.begin()
    first = True
    while block.isValid():
        nxt = block.next()
        fmt = QTextBlockFormat(block.blockFormat())
        code = _is_code(fmt)
        lst = block.textList()
        if lst is not None:
            lf = lst.format()
            if lf.indent() != 0:
                lf.setIndent(0)
                lst.setFormat(lf)
            fmt.setLeftMargin(levels.get(lst.objectIndex(), 1) * step)
        if not nxt.isValid():
            below = 0
        elif code and _is_code(nxt.blockFormat()):
            below = 0
        elif block.textList() is not None and nxt.textList() is not None:
            below = list_gap
        else:
            below = gap
        # Qt legt den Abstand unter einem Absatz und über dem nächsten zusammen (der
        # größere gilt): eine Überschrift bekommt so etwas mehr Luft als ein Absatz
        fmt.setTopMargin(0 if first or fmt.headingLevel() == 0 else round(gap * 1.5))
        fmt.setBottomMargin(below)
        if not code:
            fmt.setLineHeight(LINE_HEIGHT_PERCENT, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        cursor.setPosition(block.position())
        cursor.setBlockFormat(fmt)
        first = False
        block = nxt
    return re.sub(r'<body style="[^"]*">', "<body>", doc.toHtml(), count=1)


def self_test():
    """Leere Liste, wenn alles passt; sonst die Befunde."""
    problems = []
    html = to_html("Erster Absatz mit **fett**.\n\nZweiter Absatz.\n\n- eins\n- zwei\n\n```\na\nb\n```", 10)
    if "font-size:10pt" in html.split("<body>")[0] or "<body style" in html:
        problems.append("Schrift im Kopf des HTML nicht entfernt")
    if "margin-bottom:%dpx" % round(10 * 96 / 72 * PARAGRAPH_GAP_EM) not in html:
        problems.append("kein Absatzabstand im HTML")
    if "line-height:%d%%" % LINE_HEIGHT_PERCENT not in html:
        problems.append("keine Zeilenhöhe im HTML")
    if "<b>" not in html and "font-weight:700" not in html and "font-weight:600" not in html:
        problems.append("Fettdruck fehlt")
    return problems


if __name__ == "__main__":
    import sys
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication(sys.argv[:1] + ["-platform", "offscreen"])
    found = self_test()
    for p in found:
        print(f"FEHL  {p}")
    if not found:
        print("OK    chat_text")
    sys.exit(1 if found else 0)

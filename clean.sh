# Liste aller betroffenen Topics
TOPICS=(
    "hasp/plate/command/p1b1.text"
    "hasp/plate/command/p1b72.text"
    "hasp/plate/command/p1b11.text"
    "hasp/plate/command/p1b11.text_color"
    "hasp/plate/command/p1b13.text"
    "hasp/plate/command/p1b14.text"
    "hasp/plate/command/p1b21.text"
    "hasp/plate/command/p1b21.text_color"
    "hasp/plate/command/p1b23.text"
    "hasp/plate/command/p1b24.text"
    "hasp/plate/command/p1b31.text"
    "hasp/plate/command/p1b31.text_color"
    "hasp/plate/command/p1b33.text"
    "hasp/plate/command/p1b34.text"
    "hasp/plate/command/p1b41.text"
    "hasp/plate/command/p1b41.text_color"
    "hasp/plate/command/p1b43.text"
    "hasp/plate/command/p1b44.text"
    "hasp/plate/command/p1b51.text"
    "hasp/plate/command/p1b51.text_color"
    "hasp/plate/command/p1b53.text"
    "hasp/plate/command/p1b54.text"
)

# Broker IP
BROKER=""

echo "Lösche retained messages..."

for t in "${TOPICS[@]}"
do
    # Senden einer leeren Nachricht mit Retain-Flag löscht den Wert
    mosquitto_pub -h "$BROKER" -t "$t" -r -n
    echo "Geleert: $t"
done

echo "Fertig. Der Broker ist jetzt sauber."


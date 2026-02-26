// Configuration des broches
const int DOUT_PINS[] = {3, 5, 11, 13, 9, 7}; // 7 Non connecté
const int SCK_PINS[] = {2, 4, 10, 12, 8, 6};  // 6 Non connecté
const int NUM_SENSORS = 6;

void setup() {
  Serial.begin(9600);

  for (int i = 0; i < NUM_SENSORS; i++) {
    pinMode(DOUT_PINS[i], INPUT);
    pinMode(SCK_PINS[i], OUTPUT);
  }

  delay(1000);
}

void loop() {
  // Lire et afficher les valeurs brutes de tous les capteurs
  for (int i = 0; i < NUM_SENSORS; i++) {
    long lectureActuelle = lireValeurBrute(i);
    Serial.print(lectureActuelle);
    if (i < NUM_SENSORS - 1) {
      Serial.print(",");
    }
  }
  Serial.println();
  delay(1);
}

// --- FONCTION DE LECTURE MANUELLE (adaptée pour plusieurs capteurs) ---
long lireValeurBrute(int sensorIndex) {
  // Attendre que le capteur soit prêt
  while (digitalRead(DOUT_PINS[sensorIndex]) == HIGH) {
    // On attend que DOUT passe à LOW
  }

  unsigned long count = 0;

  // Lecture des 24 bits
  for (int i = 0; i < 24; i++) {
    digitalWrite(SCK_PINS[sensorIndex], HIGH);
    delayMicroseconds(1);
    count = count << 1;
    digitalWrite(SCK_PINS[sensorIndex], LOW);
    delayMicroseconds(1);

    if (digitalRead(DOUT_PINS[sensorIndex])) {
      count++;
    }
  }

  // 25ème pulse (Gain 128)
  digitalWrite(SCK_PINS[sensorIndex], HIGH);
  delayMicroseconds(1);
  digitalWrite(SCK_PINS[sensorIndex], LOW);
  delayMicroseconds(1);

  // Conversion (Complément à deux via XOR 0x800000)
  count = count ^ 0x800000;

  return (long)count;
}

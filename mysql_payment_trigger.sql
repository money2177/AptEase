USE aptease;
DELIMITER $$
CREATE TRIGGER prevent_overpayment BEFORE INSERT ON payments
FOR EACH ROW
BEGIN
 UPDATE bills SET paid_total = paid_total + NEW.amount
 WHERE id = NEW.bill_id AND paid_total + NEW.amount <= amount;
 IF ROW_COUNT() = 0 AND EXISTS (SELECT 1 FROM bills WHERE id = NEW.bill_id) THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Payment exceeds outstanding balance';
 END IF;
END$$
CREATE TRIGGER track_payment_update BEFORE UPDATE ON payments
FOR EACH ROW
BEGIN
 UPDATE bills SET paid_total = paid_total - OLD.amount WHERE id = OLD.bill_id;
 UPDATE bills SET paid_total = paid_total + NEW.amount
 WHERE id = NEW.bill_id AND paid_total + NEW.amount <= amount;
 IF ROW_COUNT() = 0 AND EXISTS (SELECT 1 FROM bills WHERE id = NEW.bill_id) THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Payment exceeds outstanding balance';
 END IF;
END$$
CREATE TRIGGER track_payment_delete BEFORE DELETE ON payments
FOR EACH ROW
BEGIN
 UPDATE bills SET paid_total = paid_total - OLD.amount WHERE id = OLD.bill_id;
END$$
DELIMITER ;

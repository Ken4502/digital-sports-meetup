from werkzeug.security import generate_password_hash

password = "Admin123"
hashed_password = generate_password_hash(password)

print(f"A correct hash for '{password}' looks like this:")
print(hashed_password)

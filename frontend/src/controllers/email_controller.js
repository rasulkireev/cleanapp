import { Controller } from "@hotwired/stimulus";
import { showMessage } from "../utils/messages";

export default class extends Controller {
  static targets = ["input", "list", "addButton"];

  async addEmail(event) {
    event.preventDefault();

    const emailAddress = this.inputTarget.value.trim();
    if (!emailAddress) {
      showMessage("Please enter an email address", "error");
      return;
    }

    if (!this.isValidEmail(emailAddress)) {
      showMessage("Please enter a valid email address", "error");
      return;
    }

    this.addButtonTarget.disabled = true;
    this.addButtonTarget.textContent = "Adding...";

    try {
      const response = await fetch("/api/emails/add", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": this.getCSRFToken(),
        },
        body: JSON.stringify({ email_address: emailAddress }),
      });

      const data = await response.json();

      if (response.ok && data.success) {
        showMessage(data.message, "success");
        this.inputTarget.value = "";
        this.addEmailToList(data.email_id, emailAddress, true);
      } else {
        showMessage(data.message || "Failed to add email", "error");
      }
    } catch (error) {
      console.error("Error adding email:", error);
      showMessage("An error occurred. Please try again.", "error");
    } finally {
      this.addButtonTarget.disabled = false;
      this.addButtonTarget.textContent = "Add Email";
    }
  }

  async toggleEmail(event) {
    const emailId = event.currentTarget.dataset.emailId;
    const enabled = event.currentTarget.checked;

    try {
      const response = await fetch(`/api/emails/${emailId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": this.getCSRFToken(),
        },
        body: JSON.stringify({ enabled: enabled }),
      });

      const data = await response.json();

      if (response.ok && data.success) {
        showMessage(data.message, "success");
      } else {
        showMessage(data.message || "Failed to update email", "error");
        event.currentTarget.checked = !enabled;
      }
    } catch (error) {
      console.error("Error toggling email:", error);
      showMessage("An error occurred. Please try again.", "error");
      event.currentTarget.checked = !enabled;
    }
  }

  async deleteEmail(event) {
    const emailId = event.currentTarget.dataset.emailId;
    const emailItem = event.currentTarget.closest("[data-email-item]");

    if (!confirm("Are you sure you want to remove this email address?")) {
      return;
    }

    try {
      const response = await fetch(`/api/emails/${emailId}`, {
        method: "DELETE",
        headers: {
          "X-CSRFToken": this.getCSRFToken(),
        },
      });

      const data = await response.json();

      if (response.ok && data.success) {
        showMessage(data.message, "success");
        emailItem.remove();
      } else {
        showMessage(data.message || "Failed to delete email", "error");
      }
    } catch (error) {
      console.error("Error deleting email:", error);
      showMessage("An error occurred. Please try again.", "error");
    }
  }

  addEmailToList(emailId, emailAddress, enabled) {
    const emailItem = document.createElement("div");
    emailItem.setAttribute("data-email-item", "");
    emailItem.className =
      "flex justify-between items-center p-3 bg-white rounded-md border border-gray-200";

    emailItem.innerHTML = `
      <div class="flex flex-1 items-center space-x-3">
        <input
          type="checkbox"
          ${enabled ? "checked" : ""}
          data-email-id="${emailId}"
          data-action="change->email#toggleEmail"
          class="text-blue-600 rounded border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
        />
        <div class="flex-1">
          <p class="text-sm font-medium text-gray-900">${emailAddress}</p>
          <p class="text-xs text-gray-500">
            ${
              enabled
                ? '<span class="text-green-600">Notifications enabled</span>'
                : '<span class="text-gray-500">Notifications disabled</span>'
            }
          </p>
        </div>
      </div>
      <button
        type="button"
        data-email-id="${emailId}"
        data-action="click->email#deleteEmail"
        class="text-sm font-medium text-red-600 hover:text-red-800"
      >
        Remove
      </button>
    `;

    this.listTarget.appendChild(emailItem);
  }

  isValidEmail(email) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
  }

  getCSRFToken() {
    return document.querySelector("[name=csrfmiddlewaretoken]").value;
  }
}
